import { callable } from "@decky/api";

export interface Game {
  id: string;
  name: string;
  install_path: string;
  mod_count: number;
  enabled_mod_count: number;
}

export interface Mod {
  id: string;
  name: string;
  game_id: string;
  enabled: boolean;
  installed_at: number;
  files: string[];
  source: "local" | "nexus";
  nexus_mod_id: number | null;
}

export interface HandlerInfo {
  name: string;
  tools: { id: string; label: string; description: string }[];
}

export interface SettingsView {
  nexus_api_key: string;
  nexus_api_key_set: boolean;
}

export interface NexusMod {
  mod_id: number;
  name: string;
  summary: string;
  author: string;
  downloads: number;
  endorsements: number;
  image: string | null;
  updated_at: string;
}

export interface NexusBrowseResult {
  version: string | null;
  mods: NexusMod[];
}

export interface NexusFile {
  file_id: number;
  name: string;
  version: string;
  category: string;
  is_primary: boolean;
}

export type NexusSort = "trending" | "popular" | "new" | "updated";

export type NexusInstallResult = { job: string; name: string; needs_nxm?: undefined } | { needs_nxm: true };

export interface ScriptMergerStatus {
  installed: boolean;
  exe_path: string | null;
  proton_path: string | null;
  data_dir: string;
}

export interface NativeMergerResult {
  merged_mod_name: string;
  merged_files: string[];
  conflicts_auto_resolved: string[];
  skipped_no_vanilla: string[];
  output_dir: string;
}

export interface SettingsMergerResult {
  merged_files: string[];
  conflicts_auto_resolved: string[];
  skipped_no_baseline: string[];
  baselined: string[];
}

export interface RemoveMergedResult {
  removed_merged_script_mod: boolean;
  restored_settings_files: string[];
}

export interface ModsSettingsPathInfo {
  path: string;
  exists: boolean;
  using_prefix_documents: boolean;
}

// -------- discovery --------
export const listGames = callable<[], Game[]>("list_games");
export const listMods = callable<[string], Mod[]>("list_mods");
export const getHandlerInfo = callable<[string], HandlerInfo>("get_handler_info");

// -------- local install --------
export const installMod = callable<[string, string, string | null], Mod>("install_mod");
export const uninstallMod = callable<[string, string], boolean>("uninstall_mod");
export const enableMod = callable<[string, string], Mod>("enable_mod");
export const disableMod = callable<[string, string], Mod>("disable_mod");

// -------- settings --------
export const getSettings = callable<[], SettingsView>("get_settings");
export const setNexusApiKey = callable<[string], SettingsView>("set_nexus_api_key");

// -------- nexus --------
export const nexusBrowse = callable<[string, NexusSort, boolean], NexusBrowseResult>("nexus_browse");
export const nexusSearch = callable<[string, string, boolean], NexusBrowseResult>("nexus_search");
export const nexusModFiles = callable<[string, number], NexusFile[]>("nexus_mod_files");
export const nexusInstall = callable<[string, number, number, string], NexusInstallResult>("nexus_install");
export const nexusInstallNxm = callable<[string, string, string | null], NexusInstallResult>("nexus_install_nxm");

// -------- handler tools --------
export const scriptMerger =
  callable<[string, "status" | "install" | "launch"], ScriptMergerStatus & { launched?: boolean }>(
    "script_merger",
  );
export const scriptMergerNative = callable<[string], NativeMergerResult>("script_merger_native");
export const settingsMergerNative = callable<[string], SettingsMergerResult>("settings_merger_native");
export const removeMerged = callable<[string], RemoveMergedResult>("remove_merged");
export const modsSettingsPath = callable<[string], ModsSettingsPathInfo>("mods_settings_path");
