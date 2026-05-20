import {
  ButtonItem,
  ConfirmModal,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { definePlugin } from "@decky/api";
import { Component, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { FaPuzzlePiece, FaSync, FaTrash, FaPlus, FaCog, FaDownload, FaArrowLeft, FaTools } from "react-icons/fa";
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
  NexusModFile,
  NexusSearchHit,
  nexusInstall,
  nexusModFiles,
  nexusSearch,
  scriptMerger,
  ScriptMergerStatus,
  setNexusApiKey,
  SettingsView,
  uninstallMod,
} from "./api";

// ------------------------------------------------------------ error boundary

class ErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  componentDidCatch(err: Error, info: unknown) {
    console.error("[mod-manager] render error", err, info);
  }
  render() {
    if (this.state.err) {
      return (
        <PanelSection title="Mod Manager — error">
          <PanelSectionRow>
            <div style={{ color: "#ff6b6b", fontFamily: "monospace", fontSize: 12, whiteSpace: "pre-wrap" }}>
              {String(this.state.err?.message ?? this.state.err)}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => this.setState({ err: null })}>
              Retry
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      );
    }
    return this.props.children;
  }
}

function Loading({ label = "Loading..." }: { label?: string }) {
  return <div style={{ opacity: 0.7, padding: "4px 0" }}>{label}</div>;
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
      .then((v) => { if (!cancelled) setData(v); })
      .catch((e) => { if (!cancelled) setError(String(e?.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}

// ------------------------------------------------------------ install modal

function InstallLocalModal({
  game,
  closeModal,
  onInstalled,
}: {
  game: Game;
  closeModal?: () => void;
  onInstalled: () => void;
}) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await installMod(game.id, path.trim(), name.trim() || null);
      onInstalled();
      closeModal?.();
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmModal
      strTitle={`Install mod for ${game.name}`}
      strOKButtonText={busy ? "Installing..." : "Install"}
      strCancelButtonText="Cancel"
      bOKDisabled={busy || !path.trim()}
      onOK={submit}
      onCancel={closeModal}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <TextField
          label="Archive path"
          description="Absolute path to a .zip, .7z, .rar, or .tar.* mod archive"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <TextField
          label="Display name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {err && <div style={{ color: "#ff6b6b" }}>{err}</div>}
      </div>
    </ConfirmModal>
  );
}

// ------------------------------------------------------------ nexus install modal

function NexusInstallModal({
  game,
  hit,
  closeModal,
  onInstalled,
}: {
  game: Game;
  hit: NexusSearchHit;
  closeModal?: () => void;
  onInstalled: () => void;
}) {
  const { data: files, loading, error } = useAsync(
    () => nexusModFiles(game.id, hit.mod_id),
    [game.id, hit.mod_id],
  );
  const [selected, setSelected] = useState<NexusModFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (files && !selected) {
      const primary = files.find((f) => f.is_primary) ?? files[0];
      if (primary) setSelected(primary);
    }
  }, [files, selected]);

  const submit = async () => {
    if (!selected) return;
    setBusy(true);
    setErr(null);
    try {
      await nexusInstall(game.id, hit.mod_id, selected.file_id, hit.name, null, null);
      onInstalled();
      closeModal?.();
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmModal
      strTitle={`Install "${hit.name}" from Nexus`}
      strOKButtonText={busy ? "Downloading..." : "Install"}
      strCancelButtonText="Cancel"
      bOKDisabled={busy || !selected}
      onOK={submit}
      onCancel={closeModal}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 12, opacity: 0.7 }}>
          by {hit.author} · {hit.downloads.toLocaleString()} downloads · {hit.endorsements.toLocaleString()} endorsements
        </div>
        {loading && <Loading label="Loading file list..." />}
        {error && <div style={{ color: "#ff6b6b" }}>{error}</div>}
        {files?.map((f) => (
          <div
            key={f.file_id}
            onClick={() => setSelected(f)}
            style={{
              padding: 6,
              border: "1px solid #444",
              borderColor: selected?.file_id === f.file_id ? "#67c4ff" : "#444",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            <div>{f.name}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>
              {f.category} · v{f.version || "?"} · {(f.size_kb / 1024).toFixed(1)} MB
              {f.is_primary && " · MAIN"}
            </div>
          </div>
        ))}
        {err && <div style={{ color: "#ff6b6b" }}>{err}</div>}
        <div style={{ fontSize: 11, opacity: 0.6, marginTop: 6 }}>
          Free Nexus accounts: if download fails with a "key required" error,
          you need to click an NXM:// link from the mod's page in a browser.
          Premium accounts can download directly.
        </div>
      </div>
    </ConfirmModal>
  );
}

// ------------------------------------------------------------ tabs: local mods

function LocalModsTab({ game, onChange }: { game: Game; onChange: () => void }) {
  const { data: mods, loading, error, reload } = useAsync(() => listMods(game.id), [game.id]);

  const openInstall = useCallback(() => {
    showModal(
      <InstallLocalModal
        game={game}
        onInstalled={() => {
          reload();
          onChange();
        }}
      />,
    );
  }, [game, reload, onChange]);

  return (
    <PanelSection title="Installed mods">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={openInstall}>
          <FaPlus style={{ marginRight: 6 }} /> Install from file
        </ButtonItem>
      </PanelSectionRow>
      {loading && <PanelSectionRow><Loading /></PanelSectionRow>}
      {error && <PanelSectionRow><div style={{ color: "#ff6b6b" }}>{error}</div></PanelSectionRow>}
      {!loading && mods && mods.length === 0 && (
        <PanelSectionRow>
          <div style={{ opacity: 0.7 }}>No mods installed yet.</div>
        </PanelSectionRow>
      )}
      {mods?.map((mod) => (
        <ModRow key={mod.id} mod={mod} game={game} onChange={() => { reload(); onChange(); }} />
      ))}
    </PanelSection>
  );
}

function ModRow({ mod, game, onChange }: { mod: Mod; game: Game; onChange: () => void }) {
  const [busy, setBusy] = useState(false);

  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      if (next) await enableMod(game.id, mod.id);
      else await disableMod(game.id, mod.id);
      onChange();
    } catch (e) {
      console.error("[mod-manager] toggle failed", e);
    } finally {
      setBusy(false);
    }
  };

  const remove = () => {
    showModal(
      <ConfirmModal
        strTitle={`Uninstall ${mod.name}?`}
        strDescription="Removes the mod files and restores any backed-up vanilla files."
        strOKButtonText="Uninstall"
        onOK={async () => {
          setBusy(true);
          try {
            await uninstallMod(game.id, mod.id);
            onChange();
          } finally {
            setBusy(false);
          }
        }}
      />,
    );
  };

  return (
    <>
      <PanelSectionRow>
        <ToggleField
          label={mod.name + (mod.source === "nexus" ? "  ↗ Nexus" : "")}
          description={
            busy
              ? "Working..."
              : mod.enabled
                ? `Enabled · ${mod.files.length} file(s)`
                : "Disabled"
          }
          checked={mod.enabled}
          disabled={busy}
          onChange={toggle}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={remove} disabled={busy}>
          <FaTrash style={{ marginRight: 6 }} /> Uninstall
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

// ------------------------------------------------------------ tabs: nexus

function NexusTab({ game, onChange }: { game: Game; onChange: () => void }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { data: hits, loading, error, reload } = useAsync(
    () => (submitted ? nexusSearch(game.id, submitted) : Promise.resolve([] as NexusSearchHit[])),
    [game.id, submitted],
  );

  const openHit = (hit: NexusSearchHit) => {
    showModal(
      <NexusInstallModal game={game} hit={hit} onInstalled={() => { reload(); onChange(); }} />,
    );
  };

  return (
    <PanelSection title="Browse Nexus">
      <PanelSectionRow>
        <TextField
          label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setSubmitted(query.trim())} disabled={!query.trim()}>
          <FaDownload style={{ marginRight: 6 }} /> Search
        </ButtonItem>
      </PanelSectionRow>
      {loading && <PanelSectionRow><Loading label="Searching Nexus..." /></PanelSectionRow>}
      {error && <PanelSectionRow><div style={{ color: "#ff6b6b" }}>{error}</div></PanelSectionRow>}
      {!loading && submitted && hits && hits.length === 0 && (
        <PanelSectionRow><div style={{ opacity: 0.7 }}>No results.</div></PanelSectionRow>
      )}
      {hits?.map((hit) => (
        <PanelSectionRow key={hit.mod_id}>
          <ButtonItem layout="below" onClick={() => openHit(hit)}>
            <div style={{ textAlign: "left" }}>
              <div>{hit.name}</div>
              <div style={{ fontSize: 11, opacity: 0.6 }}>
                {hit.author} · ↓{hit.downloads.toLocaleString()} · ♥{hit.endorsements.toLocaleString()}
              </div>
            </div>
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

// ------------------------------------------------------------ tabs: w3 tools

function W3ToolsTab({ game }: { game: Game }) {
  const [status, setStatus] = useState<ScriptMergerStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setStatus(await scriptMerger(game.id, "status"));
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [game.id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const doAction = async (action: "install" | "launch") => {
    setBusy(true);
    setErr(null);
    try {
      await scriptMerger(game.id, action);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message ?? e));
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Witcher 3 — Script Merger">
      {status && (
        <>
          <PanelSectionRow>
            <div style={{ fontSize: 12 }}>
              <div>Installed: {status.installed ? "yes" : "no"}</div>
              {status.exe_path && <div style={{ opacity: 0.7, wordBreak: "break-all" }}>at {status.exe_path}</div>}
              <div>Proton: {status.proton_path ? "found" : "not found"}</div>
              {status.proton_path && <div style={{ opacity: 0.7, wordBreak: "break-all" }}>at {status.proton_path}</div>}
            </div>
          </PanelSectionRow>
          {!status.installed && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => doAction("install")} disabled={busy}>
                {busy ? "Downloading..." : "Install Script Merger"}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {status.installed && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => doAction("launch")} disabled={busy || !status.proton_path}>
                {status.proton_path ? "Launch Script Merger" : "Install Proton first"}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={refresh} disabled={busy}>
          <FaSync style={{ marginRight: 6 }} /> Re-check
        </ButtonItem>
      </PanelSectionRow>
      {err && <PanelSectionRow><div style={{ color: "#ff6b6b", fontSize: 12 }}>{err}</div></PanelSectionRow>}
    </PanelSection>
  );
}

// ------------------------------------------------------------ game detail

type DetailTab = "local" | "nexus" | "tools";

function GameDetail({
  game,
  handler,
  onBack,
}: {
  game: Game;
  handler: HandlerInfo;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("local");
  const [bump, setBump] = useState(0);
  const showTools = handler.tools.length > 0;

  return (
    <ErrorBoundary>
      <PanelSection title={game.name}>
        <PanelSectionRow>
          <div style={{ fontSize: 11, opacity: 0.6, wordBreak: "break-all" }}>
            {game.install_path} · handler: {handler.name}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <TabPill label="Installed" active={tab === "local"} onClick={() => setTab("local")} />
            <TabPill label="Browse Nexus" active={tab === "nexus"} onClick={() => setTab("nexus")} />
            {showTools && (
              <TabPill label="Tools" active={tab === "tools"} onClick={() => setTab("tools")} />
            )}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onBack}>
            <FaArrowLeft style={{ marginRight: 6 }} /> Back to games
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {tab === "local" && <LocalModsTab key={bump} game={game} onChange={() => setBump((b) => b + 1)} />}
      {tab === "nexus" && <NexusTab game={game} onChange={() => setBump((b) => b + 1)} />}
      {tab === "tools" && showTools && <W3ToolsTab game={game} />}
    </ErrorBoundary>
  );
}

function TabPill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: "4px 10px",
        borderRadius: 12,
        background: active ? "#67c4ff" : "#2a2a2a",
        color: active ? "#000" : "#ddd",
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      {label}
    </div>
  );
}

// ------------------------------------------------------------ game picker

function GamePicker({ onPick }: { onPick: (g: Game) => void }) {
  const { data: games, loading, error, reload } = useAsync(() => listGames(), []);
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    if (!games) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return games;
    return games.filter((g) => g.name.toLowerCase().includes(q));
  }, [games, filter]);

  return (
    <PanelSection title="Games">
      <PanelSectionRow>
        <TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={reload}>
          <FaSync style={{ marginRight: 6 }} /> Rescan
        </ButtonItem>
      </PanelSectionRow>
      {loading && <PanelSectionRow><Loading label="Scanning Steam library..." /></PanelSectionRow>}
      {error && <PanelSectionRow><div style={{ color: "#ff6b6b" }}>{error}</div></PanelSectionRow>}
      {!loading && filtered.length === 0 && (
        <PanelSectionRow>
          <div style={{ opacity: 0.7 }}>No Steam games found.</div>
        </PanelSectionRow>
      )}
      {filtered.map((g) => (
        <PanelSectionRow key={g.id}>
          <ButtonItem layout="below" onClick={() => onPick(g)}>
            {g.name}
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}

// ------------------------------------------------------------ settings

function SettingsPanel() {
  const { data, loading, error, reload } = useAsync(() => getSettings(), []);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await setNexusApiKey(key.trim());
      setKey("");
      setMsg("Saved.");
      reload();
    } catch (e: any) {
      setMsg(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Settings">
      {loading && <PanelSectionRow><Loading /></PanelSectionRow>}
      {error && <PanelSectionRow><div style={{ color: "#ff6b6b" }}>{error}</div></PanelSectionRow>}
      {data && (
        <>
          <PanelSectionRow>
            <div style={{ fontSize: 12 }}>
              Nexus API key: {data.nexus_api_key_set ? data.nexus_api_key : "(not set)"}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField
              label="New API key"
              description="Get yours from nexusmods.com → My Account → API Access"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={save} disabled={busy || !key.trim()}>
              {busy ? "Saving..." : "Save key"}
            </ButtonItem>
          </PanelSectionRow>
          {msg && <PanelSectionRow><div style={{ fontSize: 12, opacity: 0.8 }}>{msg}</div></PanelSectionRow>}
        </>
      )}
    </PanelSection>
  );
}

// ------------------------------------------------------------ top-level

type TopTab = "games" | "settings";

function Content() {
  const [tab, setTab] = useState<TopTab>("games");
  const [selected, setSelected] = useState<Game | null>(null);
  const [handler, setHandler] = useState<HandlerInfo | null>(null);

  const pick = async (g: Game) => {
    try {
      const info = await getHandlerInfo(g.id);
      setHandler(info);
      setSelected(g);
    } catch (e) {
      console.error("[mod-manager] failed to load handler info", e);
      setHandler({ name: "generic", tools: [] });
      setSelected(g);
    }
  };

  return (
    <ErrorBoundary>
      {!selected && (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ display: "flex", gap: 4 }}>
              <TabPill label="Games" active={tab === "games"} onClick={() => setTab("games")} />
              <TabPill label="Settings" active={tab === "settings"} onClick={() => setTab("settings")} />
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}
      {selected && handler && (
        <GameDetail
          game={selected}
          handler={handler}
          onBack={() => {
            setSelected(null);
            setHandler(null);
          }}
        />
      )}
      {!selected && tab === "games" && <GamePicker onPick={pick} />}
      {!selected && tab === "settings" && <SettingsPanel />}
    </ErrorBoundary>
  );
}

export default definePlugin(() => ({
  name: "Mod Manager",
  titleView: <div>Mod Manager</div>,
  content: <Content />,
  icon: <FaPuzzlePiece />,
  onDismount() {},
}));
