p="src/main.cpp"; s=open(p).read()
old="""        const auto name = Utils::getProcessName();"""
new="""        // SteamOS-ARM-SM8650: LSFG_PROCESS is inherited by every process of a
        // Proton game. With the layer active in the Wine helpers (explorer.exe
        // spun at 100 % in its event loop) the game never got past "launching".
        // Only the game presents frames; stay out of the helpers.
        {
            std::ifstream cf("/proc/self/comm");
            std::string comm;
            std::getline(cf, comm);
            static const char* const wine_helpers[] = {
                "explorer.exe", "services.exe", "winedevice.exe", "plugplay.exe",
                "svchost.exe", "rpcss.exe", "wineboot.exe", "tabtip.exe",
                "steam.exe", "conhost.exe", "start.exe", "winedbg.exe",
                "wineserver", "rundll32.exe", "msiexec.exe", "reg.exe"
            };
            for (const char* h : wine_helpers)
                if (comm == h)
                    return; // default configuration will unload
        }

        const auto name = Utils::getProcessName();"""
assert old in s; s=s.replace(old,new,1); open(p,"w").write(s)
print("patched")
