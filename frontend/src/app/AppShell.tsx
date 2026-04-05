import type { ReactNode } from "react";

export type AppView = "library" | "setup" | "manuscript" | "graph" | "console";

type NavItem = { id: AppView; label: string; icon: string };

const libraryNav: NavItem = { id: "library", label: "故事庫", icon: "auto_stories" };

const storyScopedNav: NavItem[] = [
  { id: "setup", label: "故事設定", icon: "edit_note" },
  { id: "manuscript", label: "原稿", icon: "menu_book" },
  { id: "graph", label: "世界觀圖譜", icon: "hub" },
  { id: "console", label: "主控台", icon: "monitoring" },
];

type Props = {
  activeView: AppView;
  onViewChange: (view: AppView) => void;
  children: ReactNode;
  /** True once a story exists in the project (storyId set). Manuscript / Graph / Console require this. */
  hasSelectedStory: boolean;
  /** Show the "current story" subsection (Active Story + scoped views). True when a story is selected or user is in the new-story setup flow. */
  showStorySection: boolean;
  /** Short label for the story group heading (e.g. story title or id prefix). */
  storySectionLabel?: string;
};

function navButtonClass(active: boolean, enabled: boolean): string {
  if (!enabled) {
    return "cursor-not-allowed text-on-surface/25 opacity-50";
  }
  return active
    ? "border-b-2 border-primary pb-1 font-semibold text-primary"
    : "font-medium text-on-surface/60 transition-colors hover:text-primary";
}

function asideButtonClass(active: boolean, enabled: boolean): string {
  const base = "flex w-full items-center gap-3 py-3 text-left transition-all";
  if (!enabled) {
    return `${base} cursor-not-allowed px-6 text-on-surface/25 opacity-50`;
  }
  if (active) {
    return `${base} rounded-r-full border-l-4 border-primary bg-primary/10 px-6 text-primary`;
  }
  return `${base} px-6 text-on-surface/50 hover:bg-on-surface/5 hover:text-on-surface`;
}

export function AppShell({
  activeView,
  onViewChange,
  children,
  hasSelectedStory,
  showStorySection,
  storySectionLabel = "",
}: Props) {
  const gatedViews: AppView[] = ["manuscript", "graph", "console"];
  const needsStory = (v: AppView) => gatedViews.includes(v);

  function tryNavigate(v: AppView) {
    if (needsStory(v) && !hasSelectedStory) {
      return;
    }
    onViewChange(v);
  }

  const storyHeading =
    storySectionLabel.trim() ||
    (showStorySection && !hasSelectedStory ? "新故事" : hasSelectedStory ? "目前故事" : "");

  return (
    <div className="relative min-h-screen bg-background text-on-surface">
      <div className="pointer-events-none fixed inset-0 -z-10 opacity-30">
        <div className="absolute right-[10%] top-[20%] h-[500px] w-[500px] rounded-full bg-primary/5 blur-[120px]" />
        <div className="absolute bottom-[10%] left-[5%] h-[400px] w-[400px] rounded-full bg-secondary/5 blur-[100px]" />
      </div>

      <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-outline-variant/10 bg-[#161d2f] px-6 font-headline text-sm tracking-tight md:px-8">
        <div className="text-xl font-bold uppercase tracking-widest text-primary">The Digital Auteur</div>
        <nav className="hidden items-center gap-8 md:flex">
          <button
            type="button"
            onClick={() => tryNavigate("library")}
            className={navButtonClass(activeView === "library", true)}
          >
            {libraryNav.label}
          </button>
          {showStorySection
            ? storyScopedNav.map((item) => {
                const enabled = !needsStory(item.id) || hasSelectedStory;
                return (
                  <button
                    key={item.id}
                    type="button"
                    title={!enabled ? "請先從故事庫選擇一則故事" : undefined}
                    onClick={() => tryNavigate(item.id)}
                    disabled={!enabled}
                    className={navButtonClass(activeView === item.id, enabled)}
                  >
                    {item.label}
                  </button>
                );
              })
            : null}
        </nav>
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary">auto_fix_high</span>
        </div>
      </header>

      <div className="flex min-h-[calc(100vh-4rem)]">
        <aside className="sticky top-16 hidden h-[calc(100vh-4rem)] w-64 shrink-0 flex-col gap-1 self-start border-r border-outline-variant/10 bg-[#161d2f] py-8 font-headline text-sm font-medium text-primary shadow-glowSm lg:flex">
          <div className="mb-8 px-6">
            <div className="text-lg font-bold text-secondary">Auteur AI</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-on-surface/50">創作引擎</div>
          </div>

          <button
            type="button"
            onClick={() => tryNavigate("library")}
            className={`flex items-center gap-3 px-6 py-3 text-left transition-all ${
              activeView === "library"
                ? "rounded-r-full border-l-4 border-primary bg-primary/10 text-primary"
                : "text-on-surface/50 hover:bg-on-surface/5 hover:text-on-surface"
            }`}
          >
            <span className="material-symbols-outlined text-lg">{libraryNav.icon}</span>
            故事庫
          </button>

          {showStorySection ? (
            <div className="mt-4 border-t border-outline-variant/10 pt-4">
              <div className="mb-2 px-6 font-label text-[10px] font-semibold uppercase tracking-[0.2em] text-on-surface/40">
                {storyHeading}
              </div>
              <div className="border-l border-outline-variant/15 pl-2">
                {storyScopedNav.map((item) => {
                  const enabled = !needsStory(item.id) || hasSelectedStory;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      title={!enabled ? "請先從故事庫選擇一則故事" : undefined}
                      onClick={() => tryNavigate(item.id)}
                      disabled={!enabled}
                      className={asideButtonClass(activeView === item.id, enabled)}
                    >
                      <span className="material-symbols-outlined text-lg">{item.icon}</span>
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
        </aside>

        <main className="min-w-0 flex-1 overflow-x-hidden">{children}</main>
      </div>

      <nav className="flex flex-wrap items-center justify-center gap-3 border-t border-outline-variant/10 bg-surface-container-low py-3 font-headline text-xs font-semibold uppercase tracking-widest text-on-surface/70 lg:hidden">
        <button type="button" onClick={() => tryNavigate("library")} className={activeView === "library" ? "text-primary" : ""}>
          故事庫
        </button>
        {showStorySection
          ? storyScopedNav.map((item) => {
              const enabled = !needsStory(item.id) || hasSelectedStory;
              return (
                <button
                  key={item.id}
                  type="button"
                  disabled={!enabled}
                  title={!enabled ? "請先從故事庫選擇一則故事" : undefined}
                  onClick={() => tryNavigate(item.id)}
                  className={activeView === item.id ? "text-primary" : enabled ? "" : "opacity-40"}
                >
                  {item.label}
                </button>
              );
            })
          : null}
      </nav>

      <footer className="border-t border-outline-variant/10 py-6 text-center font-label text-xs uppercase tracking-widest text-outline">
        Auteur AI · 敘事輔助
      </footer>
    </div>
  );
}
