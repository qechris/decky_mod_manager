import {
  ButtonItem,
  ConfirmModal,
  Focusable,
  PanelSection,
  PanelSectionRow,
  Router,
  Spinner,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FaPuzzlePiece, FaSync, FaTrash, FaPlus } from "react-icons/fa";

interface Game {
  id: string;
  name: string;
  install_path: string;
}

interface Mod {
  id: string;
  name: string;
  game_id: string;
  enabled: boolean;
  installed_at: number;
  files: string[];
}

const listGames = callable<[], Game[]>("list_games");
const listMods = callable<[string], Mod[]>("list_mods");
const installMod = callable<[string, string, string | null], Mod>("install_mod");
const uninstallMod = callable<[string, string], boolean>("uninstall_mod");
const enableMod = callable<[string, string], Mod>("enable_mod");
const disableMod = callable<[string, string], Mod>("disable_mod");

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((v) => {
        if (!cancelled) setData(v);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}

function InstallModModal({
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
          description="Absolute path to a .zip, .7z, or .tar.* mod archive"
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

function ModRow({
  mod,
  game,
  onChange,
}: {
  mod: Mod;
  game: Game;
  onChange: () => void;
}) {
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
        strDescription="This removes the mod files and restores any backed-up vanilla files."
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
    <Focusable style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <PanelSectionRow>
        <ToggleField
          label={mod.name}
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
    </Focusable>
  );
}

function GameSection({ game, onBack }: { game: Game; onBack: () => void }) {
  const { data: mods, loading, error, reload } = useAsync(
    () => listMods(game.id),
    [game.id],
  );

  const openInstall = useCallback(() => {
    showModal(
      <InstallModModal game={game} onInstalled={reload} />,
    );
  }, [game, reload]);

  return (
    <>
      <PanelSection title={game.name}>
        <PanelSectionRow>
          <div style={{ fontSize: 12, opacity: 0.7, wordBreak: "break-all" }}>
            {game.install_path}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openInstall}>
            <FaPlus style={{ marginRight: 6 }} /> Install Mod
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onBack}>
            ← Back to games
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Mods">
        {loading && (
          <PanelSectionRow>
            <Spinner />
          </PanelSectionRow>
        )}
        {error && (
          <PanelSectionRow>
            <div style={{ color: "#ff6b6b" }}>{error}</div>
          </PanelSectionRow>
        )}
        {!loading && mods && mods.length === 0 && (
          <PanelSectionRow>
            <div style={{ opacity: 0.7 }}>No mods installed for this game yet.</div>
          </PanelSectionRow>
        )}
        {mods?.map((mod) => (
          <ModRow key={mod.id} mod={mod} game={game} onChange={reload} />
        ))}
      </PanelSection>
    </>
  );
}

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
        <TextField
          label="Filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={reload}>
          <FaSync style={{ marginRight: 6 }} /> Rescan
        </ButtonItem>
      </PanelSectionRow>

      {loading && (
        <PanelSectionRow>
          <Spinner />
        </PanelSectionRow>
      )}
      {error && (
        <PanelSectionRow>
          <div style={{ color: "#ff6b6b" }}>{error}</div>
        </PanelSectionRow>
      )}
      {!loading && filtered.length === 0 && (
        <PanelSectionRow>
          <div style={{ opacity: 0.7 }}>
            No Steam games found. Make sure Steam is installed under ~/.steam.
          </div>
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

function Content() {
  const [selected, setSelected] = useState<Game | null>(null);
  return selected ? (
    <GameSection game={selected} onBack={() => setSelected(null)} />
  ) : (
    <GamePicker onPick={setSelected} />
  );
}

export default definePlugin(() => {
  void Router; // keep import for potential future routing
  return {
    name: "Mod Manager",
    titleView: <div>Mod Manager</div>,
    content: <Content />,
    icon: <FaPuzzlePiece />,
    onDismount() {
      // nothing to clean up
    },
  };
});
