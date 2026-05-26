import { useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n/useI18n";

/**
 * Marketing-style entry with a single primary path into the story library.
 * Uses existing serif stack + CSS variables; avoids generic “AI landing” tropes.
 */
export function LandingPage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  return (
    <div className="relative min-h-[calc(100vh-5rem)] overflow-hidden px-6 pb-24 pt-16 md:px-12 md:pt-24">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute left-[8%] top-[12%] h-[420px] w-[420px] rounded-full bg-primary/[0.07] blur-[100px]" />
        <div className="absolute bottom-[8%] right-[6%] h-[380px] w-[380px] rounded-full bg-secondary/[0.06] blur-[90px]" />
        <div
          className="absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage: `linear-gradient(135deg, transparent 0%, rgba(192,193,255,0.04) 45%, transparent 70%),
              radial-gradient(rgba(192, 193, 255, 0.06) 1px, transparent 1px)`,
            backgroundSize: "100% 100%, 48px 48px",
          }}
        />
      </div>

      <div className="landing-hero-enter mx-auto max-w-4xl text-center">
        <p className="font-label text-[11px] font-semibold uppercase tracking-[0.42em] text-secondary/90">
          {t("landing.kicker")}
        </p>
        <h1 className="mt-6 font-headline text-4xl font-black leading-[1.08] tracking-tight text-on-surface md:text-6xl">
          {t("landing.heroTitle")}
        </h1>
        <p className="mx-auto mt-6 max-w-2xl font-body text-lg italic leading-relaxed text-on-surface-variant md:text-xl">
          {t("landing.heroSubtitle")}
        </p>

        <div className="mt-12 flex flex-col items-center gap-4">
          <button
            type="button"
            className="btn-primary-gradient px-10 py-4 text-base md:text-lg"
            onClick={() => navigate("/library")}
          >
            {t("landing.ctaPrimary")}
          </button>
          <p className="max-w-md font-body text-sm text-on-surface-variant">{t("landing.ctaHint")}</p>
        </div>
      </div>

      <div className="mx-auto mt-24 grid max-w-5xl gap-10 md:grid-cols-3 md:gap-8">
        <section className="landing-card-enter rounded-2xl border border-outline-variant/15 bg-surface-container-low/45 p-6 shadow-glow backdrop-blur-md md:p-8">
          <span className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">{t("landing.block1.kicker")}</span>
          <h2 className="mt-3 font-headline text-xl font-bold text-on-surface">{t("landing.block1.title")}</h2>
          <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("landing.block1.body")}</p>
        </section>
        <section
          className="landing-card-enter rounded-2xl border border-outline-variant/15 bg-surface-container-low/45 p-6 shadow-glow backdrop-blur-md md:p-8"
          style={{ animationDelay: "80ms" }}
        >
          <span className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">{t("landing.block2.kicker")}</span>
          <h2 className="mt-3 font-headline text-xl font-bold text-on-surface">{t("landing.block2.title")}</h2>
          <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("landing.block2.body")}</p>
        </section>
        <section
          className="landing-card-enter rounded-2xl border border-outline-variant/15 bg-surface-container-low/45 p-6 shadow-glow backdrop-blur-md md:p-8"
          style={{ animationDelay: "160ms" }}
        >
          <span className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary">{t("landing.block3.kicker")}</span>
          <h2 className="mt-3 font-headline text-xl font-bold text-on-surface">{t("landing.block3.title")}</h2>
          <p className="mt-3 font-body text-sm leading-relaxed text-on-surface-variant">{t("landing.block3.body")}</p>
        </section>
      </div>
    </div>
  );
}
