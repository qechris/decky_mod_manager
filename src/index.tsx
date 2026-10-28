import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  TextField,
  Toggle,
  showModal,
} from "@decky/ui";
import { type FileSelectionType, definePlugin, openFilePicker, toaster } from "@decky/api";

// Ambient const enum; isolatedModules can't inline it.
const PICK_FILE = 0 as FileSelectionType;
import { Component, ReactNode, useEffect, useMemo, useState } from "react";
import { FaArrowLeft, FaFolderOpen, FaPuzzlePiece, FaSearch, FaSync, FaTrash } from "react-icons/fa";
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
  NexusInstallResult,
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

// Decky backend errors carry an empty message; the text is the last traceback line.
const errText = (e: any) =>
  e?.message ||
  e?.pythonTraceback?.trim().split("\n").pop().replace(/^[\w.]+: /, "") ||
  String(e);

class ErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <PanelSection title="Something went wrong">
        <PanelSectionRow><ErrorText text={errText(this.state.err)} /></PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => this.setState({ err: null })}>Try again</ButtonItem>
        </PanelSectionRow>
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

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}

function Pills<T extends string>({
  options,
  value,
  onChange,
}: {
  options: [T, ReactNode][];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <Focusable style={{ display: "flex", gap: 4, flexWrap: "wrap" }} flow-children="horizontal">
      {options.map(([id, label]) => (
        <Focusable
          key={id}
          onActivate={() => onChange(id)}
          onClick={() => onChange(id)}
          style={{
            padding: "6px 10px",
            borderRadius: 16,
            fontSize: 13,
            background: value === id ? "#1a9fff" : "#ffffff1a",
            color: value === id ? "#fff" : "#dcdedf",
          }}
        >
          {label}
        </Focusable>
      ))}
    </Focusable>
  );
}

function installed(mod: Mod) {
  toaster.toast({ title: "Mod installed", body: `${mod.name}. Turn it on in Mods.` });
}

// ------------------------------------------------------------ mods

function ModsTab({ game }: { game: Game }) {
  const { data: mods, loading, error, reload } = useAsync(() => listMods(game.id), [game.id]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const installFile = async () => {
    setErr(null);
    try {
      const picked = await openFilePicker(
        PICK_FILE,
        "/home/deck/Downloads",
        true,
        true,
        undefined,
        ["zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "xz"],
      );
      setBusy(true);
      installed(await installMod(game.id, picked.realpath, null));
      reload();
    } catch (e) {
      if (e) setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Installed mods">
      <Row>
        <ButtonItem layout="below" onClick={installFile} disabled={busy}>
          <FaFolderOpen style={{ marginRight: 8 }} />
          {busy ? "Installing..." : "Install from file"}
        </ButtonItem>
      </Row>
      {err && <Row><ErrorText text={err} /></Row>}
      {loading && !mods && <Row><Note>Loading...</Note></Row>}
      {error && <Row><ErrorText text={error} /></Row>}
      {mods?.length === 0 && (
        <Row><Note>No mods yet. Find some in Get mods, or install a downloaded file.</Note></Row>
      )}
      {mods?.map((mod) => <ModRow key={mod.id} mod={mod} game={game} onChange={reload} />)}
    </PanelSection>
  );
}

function ModRow({ mod, game, onChange }: { mod: Mod; game: Game; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr(errText(e));
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
        onOK={() => run(() => uninstallMod(game.id, mod.id))}
      />,
    );

  return (
    <Row>
      <Field
        label={mod.name}
        description={err ? <ErrorText text={err} /> : busy ? "Working..." : mod.enabled ? "On" : "Off"}
        childrenLayout="inline"
        bottomSeparator="standard"
      >
        <Focusable style={{ display: "flex", gap: 8, alignItems: "center" }} flow-children="horizontal">
          <Toggle
            value={mod.enabled}
            disabled={busy}
            onChange={(on) => run(() => (on ? enableMod : disableMod)(game.id, mod.id))}
          />
          <DialogButton
            onClick={remove}
            disabled={busy}
            style={{ minWidth: 0, width: 40, height: 32, padding: 0 }}
          >
            <FaTrash />
          </DialogButton>
        </Focusable>
      </Field>
    </Row>
  );
}

// ------------------------------------------------------------ nexus

function NexusTab({ game, hasKey }: { game: Game; hasKey: boolean }) {
  const [sort, setSort] = useState<NexusSort>("trending");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const { data: hits, loading, error } = useAsync(
    () => (searched ? nexusSearch(game.id, searched) : nexusBrowse(game.id, sort)),
    [game.id, sort, searched],
  );

  const search = () => setSearched(query.trim());
  const pickSort = (s: NexusSort) => {
    setQuery("");
    setSearched("");
    setSort(s);
  };

  return (
    <PanelSection title="Get mods from Nexus">
      {!hasKey && (
        <Row><Note>Add your Nexus API key in Settings to download mods.</Note></Row>
      )}
      <Row>
        <TextField
          label="Search"
          value={query}
          bShowClearAction
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              search();
            }
          }}
        />
      </Row>
      <Row>
        <ButtonItem layout="below" onClick={search}>
          <FaSearch style={{ marginRight: 8 }} /> Search
        </ButtonItem>
      </Row>
      <Row>
        <Pills
          options={[["trending", "Trending"], ["popular", "Popular"], ["new", "New"], ["updated", "Updated"]]}
          value={searched ? ("" as NexusSort) : sort}
          onChange={pickSort}
        />
      </Row>
      {loading && <Row><Note>Loading...</Note></Row>}
      {error && <Row><ErrorText text={error} /></Row>}
      {!loading && !error && hits?.length === 0 && <Row><Note>Nothing found. Try other words.</Note></Row>}
      {!loading &&
        hits?.map((hit) => (
          <Row key={hit.mod_id}>
            <ButtonItem
              layout="below"
              disabled={!hasKey}
              onClick={() => showModal(<NexusInstallModal game={game} hit={hit} />)}
            >
              <div style={{ display: "flex", gap: 10, alignItems: "center", textAlign: "left" }}>
                {hit.image && (
                  <img src={hit.image} style={{ width: 56, height: 40, objectFit: "cover", borderRadius: 4 }} />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, whiteSpace: "normal" }}>{hit.name}</div>
                  <div style={{ fontSize: 12, opacity: 0.7 }}>
                    {hit.author} · {hit.downloads.toLocaleString()} downloads
                  </div>
                </div>
              </div>
            </ButtonItem>
          </Row>
        ))}
    </PanelSection>
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
    setBusy(true);
    setErr(null);
    try {
      const res: NexusInstallResult = needsNxm
        ? await nexusInstallNxm(game.id, nxm.trim(), hit.name)
        : await nexusInstall(game.id, hit.mod_id, selected!.file_id, hit.name);
      if (res.needs_nxm) {
        setNeedsNxm(true);
        return;
      }
      installed(res.mod);
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
      strOKButtonText={busy ? "Downloading..." : "Install"}
      bOKDisabled={busy || (needsNxm ? !nxm.trim() : !selected)}
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
            <Focusable
              key={f.file_id}
              onActivate={() => setSelected(f)}
              onClick={() => setSelected(f)}
              style={{
                padding: 10,
                borderRadius: 4,
                border: `2px solid ${selected?.file_id === f.file_id ? "#1a9fff" : "#ffffff1a"}`,
              }}
            >
              <div style={{ fontSize: 15 }}>{f.name}</div>
              <div style={{ fontSize: 13, opacity: 0.7 }}>
                {[f.category, f.version && `v${f.version}`, f.is_primary && "recommended"].filter(Boolean).join(" · ")}
              </div>
            </Focusable>
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

// ------------------------------------------------------------ witcher 3 tools

function W3ToolsTab({ game }: { game: Game }) {
  const { data: status, reload } = useAsync(() => scriptMerger(game.id, "status"), [game.id]);
  const { data: settingsPath } = useAsync(() => modsSettingsPath(game.id), [game.id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<string>) => {
    setBusy(label);
    setMsg(null);
    setErr(null);
    try {
      setMsg(await fn());
      reload();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  };

  const mergeScripts = () =>
    run("scripts", async () => {
      const r = await scriptMergerNative(game.id);
      return `Merged ${r.merged_files.length} script(s).` + conflictNote(r.conflicts_auto_resolved.length, r.skipped_no_vanilla.length);
    });
  const mergeSettings = () =>
    run("settings", async () => {
      const r = await settingsMergerNative(game.id);
      return `Merged ${r.merged_files.length} settings file(s).` + conflictNote(r.conflicts_auto_resolved.length, r.skipped_no_baseline.length);
    });
  const undo = () =>
    run("undo", async () => {
      const r = await removeMerged(game.id);
      return r.removed_merged_script_mod || r.restored_settings_files.length ? "Merges removed." : "Nothing to remove.";
    });

  const button = (id: string, label: string, onClick: () => void, disabled = false) => (
    <Row>
      <ButtonItem layout="below" onClick={onClick} disabled={!!busy || disabled}>
        {busy === id ? "Working..." : label}
      </ButtonItem>
    </Row>
  );

  return (
    <>
      <PanelSection title="Merge mods">
        <Row><Note>Run this after turning mods on or off. It fixes mods that change the same files.</Note></Row>
        {button("scripts", "Merge scripts", mergeScripts)}
        {button("settings", "Merge settings", mergeSettings)}
        {button("undo", "Remove merges", undo)}
        {msg && <Row><Note>{msg}</Note></Row>}
        {err && <Row><ErrorText text={err} /></Row>}
      </PanelSection>
      <PanelSection title="Script Merger app">
        <Row>
          <Note>
            The Windows Script Merger, run with Proton. {status?.installed ? "Installed." : "Not installed."}
            {status && !status.proton_path && " Proton not found."}
          </Note>
        </Row>
        {status &&
          !status.installed &&
          button("install", "Download Script Merger", () =>
            run("install", async () => (await scriptMerger(game.id, "install"), "Script Merger installed.")),
          )}
        {status?.installed &&
          button(
            "launch",
            "Open Script Merger",
            () => run("launch", async () => (await scriptMerger(game.id, "launch"), "Script Merger opened.")),
            !status.proton_path,
          )}
      </PanelSection>
      {settingsPath && (
        <PanelSection title="Load order file">
          <Row>
            <div style={{ fontSize: 12, opacity: 0.7, wordBreak: "break-all" }}>{settingsPath.path}</div>
          </Row>
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

// ------------------------------------------------------------ game

type GameTab = "mods" | "nexus" | "tools";

function GameView({ game, handler, hasKey, onBack }: { game: Game; handler: HandlerInfo; hasKey: boolean; onBack: () => void }) {
  const [tab, setTab] = useState<GameTab>("mods");
  const tabs: [GameTab | "back", ReactNode][] = [
    ["back", <FaArrowLeft style={{ verticalAlign: "middle" }} />],
    ["mods", "Mods"],
    ["nexus", "Get mods"],
  ];
  if (handler.tools.length) tabs.push(["tools", "Tools"]);

  return (
    <>
      <PanelSection title={game.name}>
        <Row>
          <Pills options={tabs} value={tab} onChange={(t) => (t === "back" ? onBack() : setTab(t))} />
        </Row>
      </PanelSection>
      {tab === "mods" && <ModsTab game={game} />}
      {tab === "nexus" && <NexusTab game={game} hasKey={hasKey} />}
      {tab === "tools" && <W3ToolsTab game={game} />}
    </>
  );
}

// ------------------------------------------------------------ games

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
      {loading && <Row><Note>Looking for games...</Note></Row>}
      {error && <Row><ErrorText text={error} /></Row>}
      {!loading && shown.length === 0 && <Row><Note>No games found.</Note></Row>}
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

// ------------------------------------------------------------ settings

function SettingsTab({ onSaved }: { onSaved: () => void }) {
  const { data, error, reload } = useAsync(() => getSettings(), []);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await setNexusApiKey(key.trim());
      setKey("");
      reload();
      onSaved();
    } catch (e) {
      setErr(errText(e));
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
        <ButtonItem layout="below" onClick={save} disabled={busy || !key.trim()}>
          {busy ? "Saving..." : "Save key"}
        </ButtonItem>
      </Row>
      {err && <Row><ErrorText text={err} /></Row>}
    </PanelSection>
  );
}

// ------------------------------------------------------------ root

function Content() {
  const [tab, setTab] = useState<"games" | "settings">("games");
  const [game, setGame] = useState<{ game: Game; handler: HandlerInfo } | null>(null);
  const { data: settings, reload: reloadSettings } = useAsync(() => getSettings(), []);
  const hasKey = !!settings?.nexus_api_key_set;

  const pick = async (g: Game) => {
    const handler = await getHandlerInfo(g.id).catch(() => ({ name: "generic", tools: [] }));
    setGame({ game: g, handler });
  };

  if (game) {
    return (
      <ErrorBoundary>
        <GameView game={game.game} handler={game.handler} hasKey={hasKey} onBack={() => setGame(null)} />
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <PanelSection>
        <Row>
          <Pills options={[["games", "Games"], ["settings", "Settings"]]} value={tab} onChange={setTab} />
        </Row>
      </PanelSection>
      {tab === "games" ? <GameList onPick={pick} /> : <SettingsTab onSaved={reloadSettings} />}
    </ErrorBoundary>
  );
}

export default definePlugin(() => ({
  name: "Mod Manager",
  titleView: <div>Mod Manager</div>,
  content: <Content />,
  icon: <FaPuzzlePiece />,
}));
