import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  Navigation,
  PanelSection,
  PanelSectionRow,
  ProgressBarWithInfo,
  TextField,
  Toggle,
  ToggleField,
  showModal,
  useParams,
} from "@decky/ui";
import {
  type FileSelectionType,
  addEventListener,
  definePlugin,
  openFilePicker,
  removeEventListener,
  routerHook,
  toaster,
} from "@decky/api";
import { Component, ReactNode, useEffect, useMemo, useState } from "react";
import { FaArrowLeft, FaDownload, FaFolderOpen, FaPuzzlePiece, FaSearch, FaSync, FaTrash } from "react-icons/fa";
import {
  disableMod,
  enableMod,
  Game,
  getHandlerInfo,
  getSettings,
  HandlerInfo,
  installMod,
  listGames,
  listMods,
  Mod,
  modsSettingsPath,
  NexusFile,
  NexusMod,
  NexusSort,
  nexusBrowse,
  nexusInstall,
  nexusInstallNxm,
  nexusModFiles,
  nexusSearch,
  removeMerged,
  scriptMerger,
  scriptMergerNative,
  setNexusApiKey,
  settingsMergerNative,
  uninstallMod,
} from "./api";

const BROWSE_ROUTE = "/mod-manager/browse/:appid";
const BLUE = "#1a9fff";

// Ambient const enum; isolatedModules can't inline it.
const PICK_FILE = 0 as FileSelectionType;

// Decky backend errors carry an empty message; the text is the last traceback line.
const errText = (e: any) =>
  e?.message ||
  e?.pythonTraceback?.trim().split("\n").pop().replace(/^[\w.]+: /, "") ||
  String(e);

// ------------------------------------------------------------ shared state

// The side menu unmounts whenever a modal or page takes focus, so where the
// user was lives outside React.
type GameTab = "mods" | "tools";
const nav: { top: "games" | "settings"; game: { game: Game; handler: HandlerInfo } | null; gameTab: GameTab } = {
  top: "games",
  game: null,
  gameTab: "mods",
};

function useNav<K extends keyof typeof nav>(key: K): [(typeof nav)[K], (v: (typeof nav)[K]) => void] {
  const [value, setValue] = useState(nav[key]);
  return [value, (v) => setValue((nav[key] = v))];
}

type Job = { name: string; progress: number };
const jobs = new Map<string, Job>();
const jobListeners = new Set<() => void>();
const notifyJobs = () => jobListeners.forEach((l) => l());

function useJobs() {
  const [, bump] = useState(0);
  useEffect(() => {
    const l = () => bump((n) => n + 1);
    jobListeners.add(l);
    return () => void jobListeners.delete(l);
  }, []);
  return [...jobs.entries()];
}

function onInstallProgress(job: string, name: string, progress: number) {
  jobs.set(job, { name, progress });
  notifyJobs();
}

function onInstallDone(job: string, name: string, error: string | null) {
  jobs.delete(job);
  notifyJobs();
  toaster.toast(
    error
      ? { title: "Install failed", body: `${name}: ${error}`, critical: true }
      : { title: "Mod installed", body: `${name} is ready. Turn it on in Mods.` },
  );
}

function startJob(job: string, name: string) {
  jobs.set(job, { name, progress: 0 });
  notifyJobs();
  toaster.toast({ title: "Downloading", body: name });
}

// ------------------------------------------------------------ small pieces

class ErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <PanelSection title="Something went wrong">
        <Row><ErrorText text={errText(this.state.err)} /></Row>
        <Row>
          <ButtonItem layout="below" onClick={() => this.setState({ err: null })}>Try again</ButtonItem>
        </Row>
      </PanelSection>
    );
  }
}

function Note({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 14, opacity: 0.8, lineHeight: 1.4 }}>{children}</div>;
}

function ErrorText({ text }: { text: string }) {
  return <div style={{ fontSize: 14, color: "#ff8080", wordBreak: "break-word" }}>{text}</div>;
}

function Row({ children }: { children: ReactNode }) {
  return <PanelSectionRow>{children}</PanelSectionRow>;
}

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((v) => !cancelled && setData(v))
      .catch((e) => !cancelled && setError(errText(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, setData, loading, error, reload: () => setNonce((n) => n + 1) };
}

function Pills<T extends string>({
  options,
  value,
  onChange,
}: {
  options: [T, ReactNode][];
  value: T | null;
  onChange: (v: T) => void;
}) {
  return (
    <Focusable style={{ display: "flex", gap: 4, flexWrap: "wrap" }} flow-children="horizontal">
      {options.map(([id, label]) => {
        const active = value === id;
        return (
          <DialogButton
            key={id}
            onClick={() => onChange(id)}
            style={{
              width: "auto",
              minWidth: 0,
              height: 32,
              padding: "0 12px",
              borderRadius: 16,
              fontSize: 13,
              fontWeight: active ? 700 : 400,
              background: active ? BLUE : undefined,
              color: active ? "#fff" : undefined,
              boxShadow: active ? "inset 0 -3px 0 #fff" : undefined,
            }}
          >
            {label}
          </DialogButton>
        );
      })}
    </Focusable>
  );
}

function Downloads() {
  const list = useJobs();
  if (!list.length) return null;
  return (
    <>
      {list.map(([id, j]) => (
        <ProgressBarWithInfo
          key={id}
          label={j.name}
          nProgress={j.progress * 100}
          indeterminate={j.progress === 0}
          sOperationText={j.progress >= 1 ? "Installing..." : `Downloading ${Math.round(j.progress * 100)}%`}
        />
      ))}
    </>
  );
}

function openBrowse(game: Game) {
  Navigation.Navigate(BROWSE_ROUTE.replace(":appid", game.id));
  Navigation.CloseSideMenus();
}

// ------------------------------------------------------------ side menu: mods

function ModsTab({ game }: { game: Game }) {
  const { data: mods, setData: setMods, loading, error, reload } = useAsync(() => listMods(game.id), [game.id]);
  const [installing, setInstalling] = useState(false);
  const running = useJobs().length;

  useEffect(() => {
    if (!running) reload();
  }, [running]);

  const installFile = async () => {
    let path: string;
    try {
      path = (
        await openFilePicker(PICK_FILE, "/home/deck/Downloads", true, true, undefined, [
          "zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "xz",
        ])
      ).realpath;
    } catch {
      return;
    }
    setInstalling(true);
    try {
      const mod = await installMod(game.id, path, null);
      toaster.toast({ title: "Mod installed", body: `${mod.name} is ready. Turn it on below.` });
      reload();
    } catch (e) {
      toaster.toast({ title: "Install failed", body: errText(e), critical: true });
    } finally {
      setInstalling(false);
    }
  };

  const update = (mod: Mod) => setMods((mods ?? []).map((m) => (m.id === mod.id ? mod : m)));

  return (
    <PanelSection title="Mods">
      <Row>
        <ButtonItem layout="below" onClick={() => openBrowse(game)}>
          <FaDownload style={{ marginRight: 8 }} /> Get mods from Nexus
        </ButtonItem>
      </Row>
      <Row>
        <ButtonItem layout="below" onClick={installFile}>
          <FaFolderOpen style={{ marginRight: 8 }} />
          {installing ? "Installing..." : "Install from file"}
        </ButtonItem>
      </Row>
      <Row><Downloads /></Row>
      {loading && !mods && <Row><Note>Loading...</Note></Row>}
      {error && <Row><ErrorText text={error} /></Row>}
      {mods?.length === 0 && <Row><Note>No mods yet. Press Get mods from Nexus to find some.</Note></Row>}
      {mods?.map((mod) => (
        <ModRow key={mod.id} mod={mod} game={game} onUpdate={update} onRemoved={reload} />
      ))}
    </PanelSection>
  );
}

function ModRow({
  mod,
  game,
  onUpdate,
  onRemoved,
}: {
  mod: Mod;
  game: Game;
  onUpdate: (m: Mod) => void;
  onRemoved: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const toggle = async (on: boolean) => {
    if (busy) return;
    setBusy(true);
    onUpdate({ ...mod, enabled: on });
    try {
      onUpdate(await (on ? enableMod : disableMod)(game.id, mod.id));
    } catch (e) {
      onUpdate(mod);
      toaster.toast({ title: `Couldn't turn ${on ? "on" : "off"} ${mod.name}`, body: errText(e), critical: true });
    } finally {
      setBusy(false);
    }
  };

  const remove = () =>
    showModal(
      <ConfirmModal
        strTitle={`Remove ${mod.name}?`}
        strDescription="This deletes the mod and puts back any game files it replaced."
        strOKButtonText="Remove"
        onOK={async () => {
          try {
            await uninstallMod(game.id, mod.id);
            toaster.toast({ title: "Mod removed", body: mod.name });
            onRemoved();
          } catch (e) {
            toaster.toast({ title: `Couldn't remove ${mod.name}`, body: errText(e), critical: true });
          }
        }}
      />,
    );

  return (
    <Row>
      <Field label={mod.name} description={mod.enabled ? "On" : "Off"} childrenLayout="inline" bottomSeparator="standard">
        <Focusable style={{ display: "flex", gap: 8, alignItems: "center" }} flow-children="horizontal">
          <Toggle value={mod.enabled} onChange={toggle} />
          <DialogButton onClick={remove} style={{ minWidth: 0, width: 40, height: 32, padding: 0 }}>
            <FaTrash />
          </DialogButton>
        </Focusable>
      </Field>
    </Row>
  );
}

// ------------------------------------------------------------ side menu: witcher 3 tools

function W3ToolsTab({ game }: { game: Game }) {
  const { data: status, reload } = useAsync(() => scriptMerger(game.id, "status"), [game.id]);
  const { data: settingsPath } = useAsync(() => modsSettingsPath(game.id), [game.id]);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (id: string, fn: () => Promise<string>) => {
    if (busy) return;
    setBusy(id);
    try {
      toaster.toast({ title: "Done", body: await fn() });
      reload();
    } catch (e) {
      toaster.toast({ title: "That didn't work", body: errText(e), critical: true });
    } finally {
      setBusy(null);
    }
  };

  const button = (id: string, label: string, fn: () => Promise<string>, disabled = false) => (
    <Row>
      <ButtonItem layout="below" onClick={() => run(id, fn)} disabled={disabled}>
        {busy === id ? "Working..." : label}
      </ButtonItem>
    </Row>
  );

  return (
    <>
      <PanelSection title="Merge mods">
        <Row><Note>Run after turning mods on or off. It fixes mods that change the same files.</Note></Row>
        {button("scripts", "Merge scripts", async () => {
          const r = await scriptMergerNative(game.id);
          return `Merged ${r.merged_files.length} script(s).` + conflictNote(r.conflicts_auto_resolved.length, r.skipped_no_vanilla.length);
        })}
        {button("settings", "Merge settings", async () => {
          const r = await settingsMergerNative(game.id);
          return `Merged ${r.merged_files.length} settings file(s).` + conflictNote(r.conflicts_auto_resolved.length, r.skipped_no_baseline.length);
        })}
        {button("undo", "Remove merges", async () => {
          const r = await removeMerged(game.id);
          return r.removed_merged_script_mod || r.restored_settings_files.length ? "Merges removed." : "Nothing to remove.";
        })}
      </PanelSection>
      <PanelSection title="Script Merger app">
        <Row>
          <Note>
            The Windows Script Merger, run with Proton. {status?.installed ? "Installed." : "Not installed."}
            {status && !status.proton_path && " Proton not found."}
          </Note>
        </Row>
        {status && !status.installed &&
          button("install", "Download Script Merger", async () => (await scriptMerger(game.id, "install"), "Script Merger installed."))}
        {status?.installed &&
          button("launch", "Open Script Merger", async () => (await scriptMerger(game.id, "launch"), "Script Merger opened."), !status.proton_path)}
      </PanelSection>
      {settingsPath && (
        <PanelSection title="Load order file">
          <Row><div style={{ fontSize: 12, opacity: 0.7, wordBreak: "break-all" }}>{settingsPath.path}</div></Row>
          {!settingsPath.using_prefix_documents && (
            <Row><Note>Start the game once so Proton makes its folders, then come back.</Note></Row>
          )}
        </PanelSection>
      )}
    </>
  );
}

function conflictNote(conflicts: number, skipped: number) {
  return (
    (conflicts ? ` ${conflicts} clash(es) solved by mod priority.` : "") +
    (skipped ? ` ${skipped} skipped (no original file).` : "")
  );
}

// ------------------------------------------------------------ side menu: game

function GameView({ game, handler, onBack }: { game: Game; handler: HandlerInfo; onBack: () => void }) {
  const [tab, setTab] = useNav("gameTab");
  const tabs: [GameTab | "back", ReactNode][] = [["back", <FaArrowLeft style={{ verticalAlign: "middle" }} />], ["mods", "Mods"]];
  if (handler.tools.length) tabs.push(["tools", "Tools"]);

  return (
    <>
      <PanelSection title={game.name}>
        <Row>
          <Pills options={tabs} value={tab} onChange={(t) => (t === "back" ? onBack() : setTab(t))} />
        </Row>
      </PanelSection>
      {tab === "tools" && handler.tools.length ? <W3ToolsTab game={game} /> : <ModsTab game={game} />}
    </>
  );
}

function GameList({ onPick }: { onPick: (g: Game) => void }) {
  const { data: games, loading, error, reload } = useAsync(() => listGames(), []);
  const [filter, setFilter] = useState("");
  const shown = useMemo(
    () => (games ?? []).filter((g) => g.name.toLowerCase().includes(filter.trim().toLowerCase())),
    [games, filter],
  );

  return (
    <PanelSection title="Games">
      <Row>
        <TextField label="Find a game" value={filter} bShowClearAction onChange={(e) => setFilter(e.target.value)} />
      </Row>
      {loading && !games && <Row><Note>Looking for games...</Note></Row>}
      {error && <Row><ErrorText text={error} /></Row>}
      {games && shown.length === 0 && <Row><Note>No games found.</Note></Row>}
      {shown.map((g) => (
        <Row key={g.id}>
          <ButtonItem layout="below" onClick={() => onPick(g)}>
            <div style={{ textAlign: "left" }}>
              <div style={{ fontSize: 14 }}>{g.name}</div>
              {g.mod_count > 0 && (
                <div style={{ fontSize: 12, opacity: 0.7 }}>
                  {g.enabled_mod_count} of {g.mod_count} mod{g.mod_count === 1 ? "" : "s"} on
                </div>
              )}
            </div>
          </ButtonItem>
        </Row>
      ))}
      <Row>
        <ButtonItem layout="below" onClick={reload}>
          <FaSync style={{ marginRight: 8 }} /> Scan again
        </ButtonItem>
      </Row>
    </PanelSection>
  );
}

function SettingsTab() {
  const { data, error, reload } = useAsync(() => getSettings(), []);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (busy || !key.trim()) return;
    setBusy(true);
    try {
      await setNexusApiKey(key.trim());
      setKey("");
      reload();
      toaster.toast({ title: "Nexus key saved", body: "You can now download mods." });
    } catch (e) {
      toaster.toast({ title: "Couldn't save the key", body: errText(e), critical: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Nexus account">
      {error && <Row><ErrorText text={error} /></Row>}
      {data && <Row><Note>API key: {data.nexus_api_key_set ? data.nexus_api_key : "not set"}</Note></Row>}
      <Row>
        <TextField
          label={data?.nexus_api_key_set ? "Replace API key" : "API key"}
          description="Find it at nexusmods.com/settings/api-keys"
          bIsPassword
          bShowClearAction
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </Row>
      <Row>
        <ButtonItem layout="below" onClick={save}>{busy ? "Saving..." : "Save key"}</ButtonItem>
      </Row>
    </PanelSection>
  );
}

function Content() {
  const [top, setTop] = useNav("top");
  const [game, setGame] = useNav("game");

  const pick = async (g: Game) => {
    const handler = await getHandlerInfo(g.id).catch(() => ({ name: "generic", tools: [] }));
    nav.gameTab = "mods";
    setGame({ game: g, handler });
  };

  return (
    <ErrorBoundary>
      {game ? (
        <GameView game={game.game} handler={game.handler} onBack={() => setGame(null)} />
      ) : (
        <>
          <PanelSection>
            <Row>
              <Pills options={[["games", "Games"], ["settings", "Settings"]]} value={top} onChange={setTop} />
            </Row>
          </PanelSection>
          {top === "games" ? <GameList onPick={pick} /> : <SettingsTab />}
        </>
      )}
    </ErrorBoundary>
  );
}

// ------------------------------------------------------------ full screen: get mods

const SORTS: [NexusSort, string][] = [["trending", "Trending"], ["popular", "Popular"], ["new", "New"], ["updated", "Updated"]];

function BrowsePage() {
  const { appid } = useParams<{ appid: string }>();
  const { data: games } = useAsync(() => listGames(), []);
  const { data: settings } = useAsync(() => getSettings(), []);
  const game = games?.find((g) => g.id === appid);
  const [sort, setSort] = useState<NexusSort>("trending");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [compatibleOnly, setCompatibleOnly] = useState(true);
  const { data, loading, error, reload } = useAsync(
    () => (searched ? nexusSearch(appid, searched, compatibleOnly) : nexusBrowse(appid, sort, compatibleOnly)),
    [appid, sort, searched, compatibleOnly],
  );
  const hasKey = !!settings?.nexus_api_key_set;

  const pickSort = (s: NexusSort) => {
    setQuery("");
    setSearched("");
    setSort(s);
  };

  return (
    <div style={{ marginTop: 40, height: "calc(100% - 40px)", overflowY: "auto", padding: "16px 24px", boxSizing: "border-box" }}>
      <div style={{ fontSize: 13, opacity: 0.7, textTransform: "uppercase", letterSpacing: 1 }}>{game?.name ?? ""}</div>
      <div style={{ fontSize: 26, fontWeight: 700, margin: "2px 0 12px" }}>Get mods</div>

      <Focusable style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }} flow-children="horizontal">
        <div style={{ flex: "1 1 320px" }}>
          <TextField
            label="Search Nexus"
            value={query}
            bShowClearAction
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                setSearched(query.trim());
              }
            }}
          />
        </div>
        <DialogButton style={{ width: "auto", minWidth: 120 }} onClick={() => setSearched(query.trim())}>
          <FaSearch style={{ marginRight: 8 }} /> Search
        </DialogButton>
      </Focusable>

      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", margin: "12px 0" }}>
        <Pills options={SORTS} value={searched ? null : sort} onChange={pickSort} />
        {data?.version && (
          <div style={{ minWidth: 300 }}>
            <ToggleField
              label={`Only mods for ${data.version}`}
              checked={compatibleOnly}
              onChange={setCompatibleOnly}
              bottomSeparator="none"
            />
          </div>
        )}
      </div>

      {!hasKey && settings && (
        <Note>Add your Nexus API key in Mod Manager settings to download. You can still look around.</Note>
      )}
      <Downloads />

      {error ? (
        <div style={{ padding: "24px 0" }}>
          <ErrorText text={error} />
          <DialogButton style={{ width: 160, marginTop: 12 }} onClick={reload}>Try again</DialogButton>
        </div>
      ) : loading ? (
        <ModGrid>{Array.from({ length: 8 }, (_, i) => <div key={i} style={cardSkeleton} />)}</ModGrid>
      ) : data?.mods.length === 0 ? (
        <Note>
          {searched ? `Nothing matched "${searched}".` : "No mods here yet."}
          {compatibleOnly && data.version && ` Turn off "Only mods for ${data.version}" to see older mods.`}
        </Note>
      ) : (
        <ModGrid>
          {data?.mods.map((m) => (
            <ModCard key={m.mod_id} mod={m} onOpen={() => game && hasKey && showModal(<NexusInstallModal game={game} hit={m} />)} />
          ))}
        </ModGrid>
      )}
    </div>
  );
}

const cardSkeleton = { height: 210, borderRadius: 4, background: "#ffffff0d" };

function ModGrid({ children }: { children: ReactNode }) {
  return (
    <Focusable
      flow-children="grid"
      style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12, paddingBottom: 24 }}
    >
      {children}
    </Focusable>
  );
}

function ModCard({ mod, onOpen }: { mod: NexusMod; onOpen: () => void }) {
  return (
    <DialogButton onClick={onOpen} style={{ padding: 0, height: 210, textAlign: "left", overflow: "hidden", display: "block" }}>
      <div style={{ height: 110, background: mod.image ? `center / cover no-repeat url("${mod.image}")` : "#ffffff0d" }} />
      <div style={{ padding: "8px 10px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.25, height: 36, overflow: "hidden" }}>{mod.name}</div>
        <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>{mod.author}</div>
        <div style={{ fontSize: 12, opacity: 0.7 }}>
          {mod.downloads.toLocaleString()} downloads · updated {mod.updated_at.slice(0, 10)}
        </div>
      </div>
    </DialogButton>
  );
}

function NexusInstallModal({ game, hit, closeModal }: { game: Game; hit: NexusMod; closeModal?: () => void }) {
  const { data: files, loading, error } = useAsync(() => nexusModFiles(game.id, hit.mod_id), [hit.mod_id]);
  const [selected, setSelected] = useState<NexusFile | null>(null);
  const [needsNxm, setNeedsNxm] = useState(false);
  const [nxm, setNxm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (files && !selected) setSelected(files[0] ?? null);
  }, [files]);

  const submit = async () => {
    if (busy || (needsNxm ? !nxm.trim() : !selected)) return;
    setBusy(true);
    setErr(null);
    try {
      const res = needsNxm
        ? await nexusInstallNxm(game.id, nxm.trim(), hit.name)
        : await nexusInstall(game.id, hit.mod_id, selected!.file_id, hit.name);
      if (res.needs_nxm) {
        setNeedsNxm(true);
        return;
      }
      startJob(res.job, res.name);
      closeModal?.();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmModal
      strTitle={hit.name}
      strOKButtonText={busy ? "Starting..." : "Install"}
      onOK={submit}
      onCancel={closeModal}
      bHideCloseIcon
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {hit.summary && <Note>{hit.summary}</Note>}
        {loading && <Note>Loading files...</Note>}
        {error && <ErrorText text={error} />}
        {!needsNxm &&
          files?.map((f) => (
            <DialogButton
              key={f.file_id}
              onClick={() => setSelected(f)}
              style={{
                textAlign: "left",
                padding: 10,
                border: `2px solid ${selected?.file_id === f.file_id ? BLUE : "transparent"}`,
              }}
            >
              <div style={{ fontSize: 15 }}>{selected?.file_id === f.file_id ? "● " : ""}{f.name}</div>
              <div style={{ fontSize: 13, opacity: 0.7 }}>
                {[f.category, f.version && `v${f.version}`, f.is_primary && "recommended"].filter(Boolean).join(" · ")}
              </div>
            </DialogButton>
          ))}
        {!loading && files?.length === 0 && <Note>This mod has no files to download.</Note>}
        {needsNxm && (
          <>
            <Note>
              Free Nexus accounts need a download link from the website. Open this mod on nexusmods.com, press
              "Mod manager download", copy the nxm:// link, and paste it here.
            </Note>
            <TextField label="nxm:// link" value={nxm} bShowClearAction onChange={(e) => setNxm(e.target.value)} />
          </>
        )}
        {err && <ErrorText text={err} />}
      </div>
    </ConfirmModal>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(BROWSE_ROUTE, BrowsePage, { exact: true });
  addEventListener("install_progress", onInstallProgress);
  addEventListener("install_done", onInstallDone);
  return {
    name: "Mod Manager",
    titleView: <div>Mod Manager</div>,
    content: <Content />,
    icon: <FaPuzzlePiece />,
    onDismount() {
      routerHook.removeRoute(BROWSE_ROUTE);
      removeEventListener("install_progress", onInstallProgress);
      removeEventListener("install_done", onInstallDone);
    },
  };
});
