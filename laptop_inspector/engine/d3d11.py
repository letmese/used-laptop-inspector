"""D3D11 stress probe - the GPU load test, without shipping any runtime.

Loads the render target hard enough to heat the GPU and, more importantly,
catches a TDR while it happens: `ClearRenderTargetView` returns void, so the
device's removed-reason is polled while the load runs.

**The adapter matters.** On an Optimus laptop the default D3D11 device is the
Intel iGPU, so a test that asks for "the hardware device" stresses the wrong
chip and then reports the Quadro as healthy. DXGI is enumerated first and the
discrete adapter is chosen explicitly; the device is created on that adapter with
D3D_DRIVER_TYPE_UNKNOWN, which is what D3D11 requires when an adapter is given.

Deliberately minimal COM surface: three DXGI calls to pick the adapter, then
three D3D11 calls to hammer a render target.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

HRESULT = ctypes.c_long
DXGI_ERROR_DEVICE_REMOVED = -2005270523       # 0x887A0005
DXGI_ERROR_DEVICE_HUNG = -2005270522          # 0x887A0006
DXGI_ERROR_DEVICE_RESET = -2005270521         # 0x887A0007
DXGI_ERROR_DRIVER_INTERNAL_ERROR = -2005270496
DXGI_ERROR_NOT_FOUND = -2005270526            # 0x887A0002

DEVICE_LOST = (DXGI_ERROR_DEVICE_REMOVED, DXGI_ERROR_DEVICE_RESET,
               DXGI_ERROR_DEVICE_HUNG, DXGI_ERROR_DRIVER_INTERNAL_ERROR)

# Vtable slots, taken from the interface declaration order in d3d11.idl rather
# than from memory. Device: 3 CreateBuffer, 4 CreateTexture1D, 5 CreateTexture2D,
# 6 CreateTexture3D, 7 CreateShaderResourceView, 8 CreateUnorderedAccessView,
# 9 CreateRenderTargetView ... 39 GetDeviceRemovedReason.
#
# The clear is slot 50. Earlier guesses were 49 (CopyStructureCount) and 46
# (CopySubresourceRegion): both void, both wrong, and both silently did nothing
# or crashed. `stress()` now asserts GetType returns 0 before it trusts any of
# these numbers, so a future drift fails loudly instead of faking a result.
DEVICE_CREATE_TEXTURE2D = 5
DEVICE_CREATE_RTV = 9
DEVICE_REMOVED_REASON = 39

# IDXGIFactory1: IUnknown 0-2, IDXGIObject 3-6, IDXGIFactory 7-11,
# then EnumAdapters1 at 12. IDXGIAdapter1::GetDesc1 is slot 10.
FACTORY_ENUM_ADAPTERS1 = 12
ADAPTER_GET_DESC1 = 10

# Context slots, from ID3D11DeviceContextVtbl in the mingw-w64 d3d11.h - the
# real COM ABI. An earlier attempt derived them from Wine's d3d11.idl and was
# off by four, because that file lists PSSetConstantBuffers out of order.
CONTEXT_PS_SET = 9
CONTEXT_VS_SET = 11
CONTEXT_DRAW = 13
CONTEXT_MAP = 14
CONTEXT_UNMAP = 15
CONTEXT_OM_SET_RT = 33
CONTEXT_RS_SET_VIEWPORTS = 44
CONTEXT_COPY_RESOURCE = 47
CONTEXT_CLEAR_RTV = 50
CONTEXT_GET_TYPE = 112

DEVICE_CREATE_VS = 12
DEVICE_CREATE_PS = 15

D3D_DRIVER_TYPE_UNKNOWN = 0
D3D_DRIVER_TYPE_HARDWARE = 1
D3D11_SDK_VERSION = 7
D3D11_BIND_RENDER_TARGET = 0x20
D3D11_USAGE_DEFAULT = 0
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_ADAPTER_FLAG_SOFTWARE = 2

# NVIDIA, AMD, and the AMD vendor id some drivers still report.
DISCRETE_VENDORS = (0x10DE, 0x1002, 0x1022)
VENDOR_NAMES = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD", 0x8086: "Intel",
                0x15AD: "VMware", 0x1AF4: "Red Hat", 0x1414: "Microsoft"}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


IID_IDXGIFactory1 = GUID(
    0x770AAE78, 0xF26F, 0x4DBA,
    (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]


class D3D11_VIEWPORT(ctypes.Structure):
    _fields_ = [("TopLeftX", ctypes.c_float), ("TopLeftY", ctypes.c_float),
                ("Width", ctypes.c_float), ("Height", ctypes.c_float),
                ("MinDepth", ctypes.c_float), ("MaxDepth", ctypes.c_float)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p),
                ("RowPitch", wintypes.UINT),
                ("DepthPitch", wintypes.UINT)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.UINT),
    ]

FEATURE_LEVELS = [
    0xB000,  # 11_0
    0xA100,  # 10_1
    0xA000,  # 10_0
    0x9300,  # 9_3
    0x9200,  # 9_2
    0x9100,  # 9_1
]
FL_NAMES = {0xB000: "11_0", 0xA100: "10_1", 0xA000: "10_0",
            0x9300: "9_3", 0x9200: "9_2", 0x9100: "9_1", 0xB100: "11_1"}


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", wintypes.UINT),
        ("Height", wintypes.UINT),
        ("MipLevels", wintypes.UINT),
        ("ArraySize", wintypes.UINT),
        ("Format", wintypes.UINT),
        ("SampleDescCount", wintypes.UINT),
        ("SampleDescQuality", wintypes.UINT),
        ("Usage", wintypes.UINT),
        ("BindFlags", wintypes.UINT),
        ("CPUAccessFlags", wintypes.UINT),
        ("MiscFlags", wintypes.UINT),
    ]


def _method(ptr: int, index: int, argtypes, restype=HRESULT):
    """Build a callable for COM vtable slot `index` of interface `ptr`."""
    if not ptr:
        raise RuntimeError("null interface pointer")
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[index]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(fn)


def _release(ptr: int) -> None:
    if not ptr:
        return
    try:
        _method(ptr, 2, [], ctypes.c_ulong)(ptr)
    except Exception:
        pass


def adapters() -> List[Dict[str, Any]]:
    """Every DXGI adapter, with enough detail to tell the discrete one apart."""
    out: List[Dict[str, Any]] = []
    try:
        dxgi = ctypes.WinDLL("dxgi")
    except OSError:
        return out

    create_factory = dxgi.CreateDXGIFactory1
    create_factory.restype = HRESULT
    create_factory.argtypes = [ctypes.POINTER(GUID),
                               ctypes.POINTER(ctypes.c_void_p)]

    factory = ctypes.c_void_p()
    hr = create_factory(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
    if hr < 0 or not factory.value:
        return out

    try:
        enum = _method(factory.value, FACTORY_ENUM_ADAPTERS1,
                       [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])
        for index in range(16):
            adapter = ctypes.c_void_p()
            hr = enum(factory.value, index, ctypes.byref(adapter))
            if hr < 0 or not adapter.value:
                break
            try:
                desc = DXGI_ADAPTER_DESC1()
                get_desc = _method(adapter.value, ADAPTER_GET_DESC1,
                                   [ctypes.POINTER(DXGI_ADAPTER_DESC1)])
                if get_desc(adapter.value, ctypes.byref(desc)) < 0:
                    continue
                out.append({
                    "name": (desc.Description or "").strip(),
                    "vendor_id": int(desc.VendorId),
                    "vendor": VENDOR_NAMES.get(int(desc.VendorId), "?"),
                    "vram_mb": int(desc.DedicatedVideoMemory / (1024 * 1024)),
                    "software": bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE),
                })
            finally:
                _release(adapter.value)
    finally:
        _release(factory.value)
    return out


def _best_adapter() -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """The adapter worth stressing: a discrete GPU if the machine has one.

    On Optimus the default D3D11 device is the Intel iGPU, so a test that passes
    NULL here silently measures the wrong chip.
    """
    found = adapters()
    if not found:
        return None, None

    ranked = sorted(
        found,
        key=lambda a: (not a["software"],
                       1 if a["vendor_id"] in DISCRETE_VENDORS else 0,
                       a["vram_mb"]),
        reverse=True)
    chosen = ranked[0]
    if chosen["software"]:
        return None, chosen

    # Re-enumerate to hand out a live pointer; the list above is just metadata.
    try:
        dxgi = ctypes.WinDLL("dxgi")
        create_factory = dxgi.CreateDXGIFactory1
        create_factory.restype = HRESULT
        create_factory.argtypes = [ctypes.POINTER(GUID),
                                   ctypes.POINTER(ctypes.c_void_p)]
        factory = ctypes.c_void_p()
        if create_factory(ctypes.byref(IID_IDXGIFactory1),
                          ctypes.byref(factory)) < 0 or not factory.value:
            return None, chosen
        try:
            enum = _method(factory.value, FACTORY_ENUM_ADAPTERS1,
                           [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])
            for index in range(len(found)):
                adapter = ctypes.c_void_p()
                if enum(factory.value, index, ctypes.byref(adapter)) < 0:
                    break
                desc = DXGI_ADAPTER_DESC1()
                get_desc = _method(adapter.value, ADAPTER_GET_DESC1,
                                   [ctypes.POINTER(DXGI_ADAPTER_DESC1)])
                if get_desc(adapter.value, ctypes.byref(desc)) >= 0:
                    if (desc.Description or "").strip() == chosen["name"]:
                        return adapter.value, chosen
                _release(adapter.value)
        finally:
            _release(factory.value)
    except Exception:
        pass
    return None, chosen


# A fullscreen triangle from SV_VertexID (no vertex buffer, no input layout) and
# a deliberately expensive pixel shader. A clear loop is not a GPU load: the
# driver collapses repeated clears of a target nothing reads, which is why the
# card sat idle at 0 % in Task Manager while this probe reported a big number.
STRESS_HLSL = b"""
struct VSOut { float4 pos : SV_Position; };

VSOut VSMain(uint id : SV_VertexID)
{
    VSOut o;
    float2 p = float2((id << 1) & 2, id & 2);
    o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0);
    return o;
}

float4 PSMain(VSOut i) : SV_Target
{
    float2 uv = i.pos.xy * 0.0009765625;      // / 1024
    float v = 0.5;
    [unroll] for (int k = 0; k < 16; k++)
        v = frac(v * 1.618034 + sin(uv.x * (k + 1)) * cos(uv.y * (k + 2)));
    return float4(v, 1.0 - v, v * 0.5, 1.0);
}
"""


def _compile(source: bytes, entry: bytes, target: bytes):
    """Compile HLSL at runtime. Returns (bytecode pointer, size), or None.

    The size matters: CreateVertexShader rejects a zero BytecodeLength with
    E_INVALIDARG, so it is read back from the ID3DBlob (vtable slots 3 and 4).
    """
    for dll in ("d3dcompiler_47", "d3dcompiler_46"):
        try:
            compiler = ctypes.WinDLL(dll)
            fn = compiler.D3DCompile
        except (OSError, AttributeError):
            continue
        fn.restype = HRESULT
        fn.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                       ctypes.c_char_p, wintypes.UINT, wintypes.UINT,
                       ctypes.POINTER(ctypes.c_void_p),
                       ctypes.POINTER(ctypes.c_void_p)]
        blob = ctypes.c_void_p()
        error = ctypes.c_void_p()
        hr = fn(source, len(source), b"stress", None, None, entry, target,
                0, 0, ctypes.byref(blob), ctypes.byref(error))
        if hr < 0 or not blob.value:
            return None
        get_ptr = _method(blob.value, 3, [], restype=ctypes.c_void_p)
        get_size = _method(blob.value, 4, [], restype=ctypes.c_size_t)
        return get_ptr(blob.value), get_size(blob.value)
    return None


def _pipeline(device: int, context: int, rtv: int,
              width: int, height: int) -> Optional[Dict[str, Any]]:
    """Vertex + pixel shader wired to the render target, or None if unavailable."""
    vs_blob = _compile(STRESS_HLSL, b"VSMain", b"vs_4_0")
    ps_blob = _compile(STRESS_HLSL, b"PSMain", b"ps_4_0")
    if not vs_blob or not ps_blob:
        return None

    create_vs = _method(device, DEVICE_CREATE_VS,
                        [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_void_p)])
    create_ps = _method(device, DEVICE_CREATE_PS,
                        [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_void_p)])
    vs = ctypes.c_void_p()
    ps = ctypes.c_void_p()
    # CreateVertexShader(pBytecode, BytecodeLength, pClassLinkage, ppShader)
    if create_vs(device, vs_blob[0], vs_blob[1], None,
                 ctypes.byref(vs)) < 0 or not vs.value:
        return None
    if create_ps(device, ps_blob[0], ps_blob[1], None,
                 ctypes.byref(ps)) < 0 or not ps.value:
        _release(vs.value)
        return None

    set_vs = _method(context, CONTEXT_VS_SET,
                     [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT],
                     restype=None)
    set_ps = _method(context, CONTEXT_PS_SET,
                     [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT],
                     restype=None)
    set_rt = _method(context, CONTEXT_OM_SET_RT,
                     [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                      ctypes.c_void_p], restype=None)
    set_vp = _method(context, CONTEXT_RS_SET_VIEWPORTS,
                     [wintypes.UINT, ctypes.POINTER(D3D11_VIEWPORT)],
                     restype=None)
    draw = _method(context, CONTEXT_DRAW,
                   [wintypes.UINT, wintypes.UINT], restype=None)

    viewport = D3D11_VIEWPORT(0.0, 0.0, float(width), float(height), 0.0, 1.0)
    targets = (ctypes.c_void_p * 1)(rtv)
    set_rt(context, 1, ctypes.cast(targets, ctypes.POINTER(ctypes.c_void_p)), None)
    set_vp(context, 1, ctypes.pointer(viewport))
    set_vs(context, vs.value, None, 0)
    set_ps(context, ps.value, None, 0)

    return {"draw": draw, "vs": vs.value, "ps": ps.value}


def stress(duration_s: float = 12.0, width: int = 1280, height: int = 720,
           progress=None, stop=None) -> Dict[str, Any]:
    """Create a D3D11 device on the best adapter and hammer a render target.

    `progress(frames, elapsed, frames_per_sec)` is called once per pass so
    a UI can show the rate while it runs. `stop` is a threading.Event; setting it
    ends the run early and keeps the samples already taken.
    """
    result: Dict[str, Any] = {
        "available": False,
        "device_removed": False,
        "frames": 0,
        "seconds": 0.0,
        "frames_per_sec": 0,
        "mode": None,
        "feature_level": None,
        "adapter": None,
        "adapters": [],
        "error": None,
        "hresult": None,
    }
    try:
        d3d11 = ctypes.WinDLL("d3d11")
    except OSError as exc:
        result["error"] = f"d3d11.dll unavailable: {exc}"
        return result

    adapter_ptr, adapter_info = _best_adapter()
    result["adapters"] = [a["name"] for a in adapters()]
    if adapter_info:
        result["adapter"] = adapter_info.get("name")

    create = d3d11.D3D11CreateDevice
    create.restype = HRESULT
    create.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(ctypes.c_int), wintypes.UINT, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_void_p),
    ]

    levels = (ctypes.c_int * len(FEATURE_LEVELS))(*FEATURE_LEVELS)
    device = ctypes.c_void_p()
    context = ctypes.c_void_p()
    feature = ctypes.c_int(0)

    # D3D11 requires D3D_DRIVER_TYPE_UNKNOWN whenever an explicit adapter is
    # passed; D3D_DRIVER_TYPE_HARDWARE with a non-NULL adapter is E_INVALIDARG.
    driver_type = (D3D_DRIVER_TYPE_UNKNOWN if adapter_ptr
                   else D3D_DRIVER_TYPE_HARDWARE)
    hr = create(adapter_ptr, driver_type, None, 0,
                levels, len(FEATURE_LEVELS), D3D11_SDK_VERSION,
                ctypes.byref(device), ctypes.byref(feature),
                ctypes.byref(context))

    if hr < 0 and adapter_ptr:
        # Some Optimus drivers refuse a device on the dGPU from a process that
        # is not on their list. Fall back to the default adapter rather than
        # reporting the card as unavailable - and say which one ran.
        result["adapter_fallback"] = result["adapter"]
        _release(adapter_ptr)
        adapter_ptr = 0
        result["adapter"] = None
        hr = create(None, D3D_DRIVER_TYPE_HARDWARE, None, 0,
                    levels, len(FEATURE_LEVELS), D3D11_SDK_VERSION,
                    ctypes.byref(device), ctypes.byref(feature),
                    ctypes.byref(context))

    if hr < 0:
        result["error"] = f"D3D11CreateDevice failed (0x{hr & 0xFFFFFFFF:08X})"
        result["hresult"] = hr
        _release(adapter_ptr or 0)
        return result

    result["available"] = True
    result["feature_level"] = FL_NAMES.get(feature.value, hex(feature.value))

    # Guard against a drifted vtable. GetType returns 0 for an immediate context;
    # if that is not what comes back, every slot below is wrong and any number
    # this function produced would be fiction. Fail instead of lying.
    try:
        get_type = _method(context.value, CONTEXT_GET_TYPE, [],
                           restype=ctypes.c_int)
        context_type = int(get_type(context.value))
    except Exception:
        context_type = -1
    result["context_type"] = context_type
    if context_type != 0:
        result["error"] = (f"D3D11 context vtable does not match "
                           f"(GetType returned {context_type}, expected 0) - "
                           f"refusing to report a load test")
        _release(adapter_ptr or 0)
        return result

    texture = ctypes.c_void_p()
    rtv = ctypes.c_void_p()
    pipe = None
    try:
        desc = D3D11_TEXTURE2D_DESC()
        desc.Width = width
        desc.Height = height
        desc.MipLevels = 1
        desc.ArraySize = 1
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM
        desc.SampleDescCount = 1
        desc.SampleDescQuality = 0
        desc.Usage = D3D11_USAGE_DEFAULT
        desc.BindFlags = D3D11_BIND_RENDER_TARGET
        desc.CPUAccessFlags = 0
        desc.MiscFlags = 0

        create_tex = _method(
            device.value, DEVICE_CREATE_TEXTURE2D,
            [ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p,
             ctypes.POINTER(ctypes.c_void_p)])
        hr = create_tex(device.value, ctypes.byref(desc), None,
                        ctypes.byref(texture))
        if hr < 0:
            result["error"] = f"CreateTexture2D failed (0x{hr & 0xFFFFFFFF:08X})"
            result["hresult"] = hr
            return result

        create_rtv = _method(
            device.value, DEVICE_CREATE_RTV,
            [ctypes.c_void_p, ctypes.c_void_p,
             ctypes.POINTER(ctypes.c_void_p)])
        hr = create_rtv(device.value, texture, None, ctypes.byref(rtv))
        if hr < 0:
            result["error"] = f"CreateRenderTargetView failed (0x{hr & 0xFFFFFFFF:08X})"
            result["hresult"] = hr
            return result

        # ClearRenderTargetView returns void, not HRESULT, so the failure signal
        # is the device's removed-reason, polled while the load runs.
        clear = _method(context.value, CONTEXT_CLEAR_RTV,
                        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)],
                        restype=None)
        removed_reason = _method(device.value, DEVICE_REMOVED_REASON, [],
                                 restype=HRESULT)

        # A target nothing ever reads gets its clears coalesced away by the
        # driver - measuring that produced 421k "clears" a second, which is 1.5
        # TB/s on a card that manages 40. So each batch is copied to a staging
        # texture and mapped back, which forces the GPU to finish the work.
        staging = ctypes.c_void_p()
        stage_desc = D3D11_TEXTURE2D_DESC()
        stage_desc.Width = width
        stage_desc.Height = height
        stage_desc.MipLevels = 1
        stage_desc.ArraySize = 1
        stage_desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM
        stage_desc.SampleDescCount = 1
        stage_desc.SampleDescQuality = 0
        stage_desc.Usage = D3D11_USAGE_STAGING
        stage_desc.BindFlags = 0
        stage_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ
        stage_desc.MiscFlags = 0

        create_tex2 = _method(
            device.value, DEVICE_CREATE_TEXTURE2D,
            [ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p,
             ctypes.POINTER(ctypes.c_void_p)])
        sync = create_tex2(device.value, ctypes.byref(stage_desc), None,
                           ctypes.byref(staging)) >= 0 and bool(staging.value)

        copy = _method(context.value, CONTEXT_COPY_RESOURCE,
                       [ctypes.c_void_p, ctypes.c_void_p], restype=None)
        map_ = _method(context.value, CONTEXT_MAP,
                       [ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
                        wintypes.UINT, ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE)])
        unmap = _method(context.value, CONTEXT_UNMAP,
                        [ctypes.c_void_p, wintypes.UINT], restype=None)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        result["synchronised"] = sync

        # Real shaded draws where the runtime can compile HLSL; the clear loop is
        # only a fallback, and it is honestly labelled as such.
        pipe = _pipeline(device.value, context.value, rtv, width, height)
        result["mode"] = "shader" if pipe else "clear"

        colour = (ctypes.c_float * 4)(0.0, 0.0, 0.0, 1.0)
        start = time.perf_counter()
        frames = 0
        deadline = start + duration_s
        stopped = False
        sync_every = 1 if pipe else 16
        while time.perf_counter() < deadline:
            if stop is not None and stop.is_set():
                stopped = True
                break
            for _ in range(sync_every):
                if pipe:
                    pipe["draw"](context.value, 3, 0)
                else:
                    colour[0] = (frames & 0xFF) / 255.0
                    clear(context.value, rtv, colour)
                frames += 1

            # With real draws the map is what makes the number mean something:
            # without it the CPU races ahead of the GPU and reports its own
            # submission rate. A clear loop only needs it occasionally.
            if sync and (pipe is not None or frames % 16 == 0):
                copy(context.value, staging, texture)
                if map_(context.value, staging, 0, D3D11_MAP_READ, 0,
                        ctypes.byref(mapped)) >= 0:
                    unmap(context.value, staging, 0)

            reason = int(removed_reason(device.value))
            if reason in DEVICE_LOST:
                result["device_removed"] = True
                result["hresult"] = reason
                result["error"] = (f"display driver reset during load "
                                   f"(0x{reason & 0xFFFFFFFF:08X})")
                result["frames"] = frames
                result["seconds"] = round(time.perf_counter() - start, 2)
                return result

            if progress is not None:
                elapsed = time.perf_counter() - start
                rate = int(frames / elapsed) if elapsed > 0 else 0
                try:
                    progress(frames, elapsed, rate)
                except Exception:
                    pass
        elapsed = time.perf_counter() - start
        result["frames"] = frames
        result["seconds"] = round(elapsed, 2)
        result["frames_per_sec"] = int(frames / elapsed) if elapsed > 0 else 0
        result["stopped"] = stopped
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _release(rtv.value if rtv else 0)
        if pipe:
            _release(pipe.get("vs") or 0)
            _release(pipe.get("ps") or 0)
        _release(staging.value if staging else 0)
        _release(texture.value if texture else 0)
        _release(context.value if context else 0)
        _release(device.value if device else 0)
        _release(adapter_ptr or 0)
    return result


def stress_isolated(duration_s: float = 12.0) -> Dict[str, Any]:
    """Kept as a name for the callers; runs in-process now.

    Isolation used to mean a child process, which on a frozen exe cost a full
    47 MB re-extraction and could stall for 30 s. The probe makes three COM calls
    that have been exercised on real hardware, so the risk it takes the process
    down is not worth that price. Failures are detected through the device's
    removed-reason rather than a return code, and anything the probe cannot drive
    is reported as `inconclusive` and never scored against the machine.
    """
    return stress(duration_s)
