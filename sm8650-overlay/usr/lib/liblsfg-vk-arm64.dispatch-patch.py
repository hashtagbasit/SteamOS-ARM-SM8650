# SteamOS-ARM-SM8650 patch for lsfg-vk (xXJSONDeruloXx fork, tag fp16-test-2), src/layer.cpp
#
# 1. Per-chain dispatch. Upstream keeps the next layer's vkGetInstanceProcAddr /
#    vkGetDeviceProcAddr / vkCreateDevice in single globals that every
#    vkCreateInstance / vkCreateDevice overwrites. Wine's explorer.exe (Proton
#    ARM64) builds two independent chains (winevulkan's GPU query and zink behind
#    EGL); lsfg then forwarded one chain's device into MangoHud's GetDeviceProcAddr
#    from the other chain -> NULL deref in overlay_GetDeviceProcAddr -> winex11.drv
#    init fails -> dangling driver pointer -> SIGSEGV loop, game stuck "launching".
#    Now each instance/device keeps its own next-layer proc addr, keyed by the
#    loader dispatch key.
# 2. Only hook devices that enable VK_KHR_swapchain. Upstream failed vkCreateDevice
#    (-3) for any device without swapchain functions and let such a device
#    overwrite the globals used for the real rendering device.
import re, sys

p = "src/layer.cpp"
s = open(p).read()

def sub(old, new, count=1):
    global s
    if old not in s:
        sys.exit("patch anchor not found:\n" + old)
    s = s.replace(old, new, count)

sub("#include <unordered_map>\n", "#include <unordered_map>\n#include <mutex>\n#include <cstring>\n")

sub("""    PFN_vkAcquireNextImageKHR next_vkAcquireNextImageKHR{};
""", """    PFN_vkAcquireNextImageKHR next_vkAcquireNextImageKHR{};

    // per-chain dispatch (keyed by the loader dispatch pointer of the handle)
    std::mutex dispatchMutex;
    std::unordered_map<void*, PFN_vkGetInstanceProcAddr> instanceGipa;
    std::unordered_map<void*, PFN_vkGetDeviceProcAddr> deviceGdpa;
    std::unordered_map<void*, bool> deviceHooked;

    void* dispatchKey(const void* handle) {
        return handle ? *reinterpret_cast<void* const*>(handle) : nullptr;
    }

    bool hasExtension(const VkDeviceCreateInfo* info, const char* name) {
        for (uint32_t i = 0; i < info->enabledExtensionCount; i++)
            if (std::strcmp(info->ppEnabledExtensionNames[i], name) == 0)
                return true;
        return false;
    }
""")

# --- vkCreateInstance: remember this chain's gipa --------------------------
sub("""            next_vkGetInstanceProcAddr = layerDesc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
            layerDesc->u.pLayerInfo = layerDesc->u.pLayerInfo->pNext;
""", """            const PFN_vkGetInstanceProcAddr chainGipa = layerDesc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
            next_vkGetInstanceProcAddr = chainGipa;
            layerDesc->u.pLayerInfo = layerDesc->u.pLayerInfo->pNext;
""")
sub("""            if (!Config::activeConf.enable) {
                auto res = next_vkCreateInstance(pCreateInfo, pAllocator, pInstance);
                initInstanceFunc(*pInstance, "vkCreateDevice", &next_vkCreateDevice);
                return res;
            }
""", """            if (!Config::activeConf.enable) {
                auto res = next_vkCreateInstance(pCreateInfo, pAllocator, pInstance);
                if (res == VK_SUCCESS) {
                    std::lock_guard<std::mutex> lock(dispatchMutex);
                    instanceGipa[dispatchKey(*pInstance)] = chainGipa;
                }
                return res;
            }
""")
sub("""                auto res = createInstanceHook(pCreateInfo, pAllocator, pInstance);
                if (res != VK_SUCCESS)
                    throw LSFG::vulkan_error(res, "Unknown error");
""", """                auto res = createInstanceHook(pCreateInfo, pAllocator, pInstance);
                if (res != VK_SUCCESS)
                    throw LSFG::vulkan_error(res, "Unknown error");
                std::lock_guard<std::mutex> lock(dispatchMutex);
                instanceGipa[dispatchKey(*pInstance)] = chainGipa;
""")

# --- vkCreateDevice: this chain's gdpa / createDevice, swapchain-only hooking --
sub("""            next_vkGetDeviceProcAddr = layerDesc->u.pLayerInfo->pfnNextGetDeviceProcAddr;
            layerDesc->u.pLayerInfo = layerDesc->u.pLayerInfo->pNext;
""", """            const PFN_vkGetDeviceProcAddr chainGdpa = layerDesc->u.pLayerInfo->pfnNextGetDeviceProcAddr;
            const PFN_vkGetInstanceProcAddr chainGipa = layerDesc->u.pLayerInfo->pfnNextGetInstanceProcAddr;
            layerDesc->u.pLayerInfo = layerDesc->u.pLayerInfo->pNext;
            const auto chainCreateDevice = reinterpret_cast<PFN_vkCreateDevice>(
                chainGipa(nullptr, "vkCreateDevice"));
            if (!chainCreateDevice)
                throw LSFG::vulkan_error(VK_ERROR_INITIALIZATION_FAILED,
                    "No vkCreateDevice in the next layer");
""")
sub("""            // NOLINTEND | skip initialization if the layer is disabled
            if (!Config::activeConf.enable)
                return next_vkCreateDevice(physicalDevice, pCreateInfo, pAllocator, pDevice);
""", """            // NOLINTEND | pass through if the layer is disabled, or for devices that
            // cannot present (compute/query devices): only swapchain devices are hooked
            if (!Config::activeConf.enable || !hasExtension(pCreateInfo, "VK_KHR_swapchain")) {
                auto res = chainCreateDevice(physicalDevice, pCreateInfo, pAllocator, pDevice);
                if (res == VK_SUCCESS) {
                    std::lock_guard<std::mutex> lock(dispatchMutex);
                    deviceGdpa[dispatchKey(*pDevice)] = chainGdpa;
                    deviceHooked[dispatchKey(*pDevice)] = false;
                }
                return res;
            }
            next_vkGetDeviceProcAddr = chainGdpa;
            next_vkCreateDevice = chainCreateDevice;
""")
sub("""            std::cerr << "lsfg-vk: Vulkan device layer initialized successfully.\\n";
""", """            {
                std::lock_guard<std::mutex> lock(dispatchMutex);
                deviceGdpa[dispatchKey(*pDevice)] = chainGdpa;
                deviceHooked[dispatchKey(*pDevice)] = true;
            }
            std::cerr << "lsfg-vk: Vulkan device layer initialized successfully.\\n";
""")

# --- proc addr lookups use the handle's own chain -----------------------------
sub("""    it = Hooks::hooks.find(name);
    if (it != Hooks::hooks.end() && Config::activeConf.enable)
        return it->second;

    return next_vkGetInstanceProcAddr(instance, pName);
}""", """    it = Hooks::hooks.find(name);
    if (it != Hooks::hooks.end() && Config::activeConf.enable)
        return it->second;

    PFN_vkGetInstanceProcAddr gipa = next_vkGetInstanceProcAddr;
    if (instance) {
        std::lock_guard<std::mutex> lock(dispatchMutex);
        auto found = instanceGipa.find(dispatchKey(instance));
        if (found != instanceGipa.end())
            gipa = found->second;
    }
    return gipa ? gipa(instance, pName) : nullptr;
}""")
sub("""    it = Hooks::hooks.find(name);
    if (it != Hooks::hooks.end() && Config::activeConf.enable)
        return it->second;

    return next_vkGetDeviceProcAddr(device, pName);
}""", """    PFN_vkGetDeviceProcAddr gdpa = next_vkGetDeviceProcAddr;
    bool hooked = true;
    if (device) {
        std::lock_guard<std::mutex> lock(dispatchMutex);
        auto found = deviceGdpa.find(dispatchKey(device));
        if (found != deviceGdpa.end()) {
            gdpa = found->second;
            hooked = deviceHooked[dispatchKey(device)];
        }
    }

    it = Hooks::hooks.find(name);
    if (it != Hooks::hooks.end() && Config::activeConf.enable && hooked)
        return it->second;

    return gdpa ? gdpa(device, pName) : nullptr;
}""")

open(p, "w").write(s)
print("layer.cpp patched")
