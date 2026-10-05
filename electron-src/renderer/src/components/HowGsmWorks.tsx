import { useCallback, useState, type SyntheticEvent } from "react";
import { invokeIpc } from "../lib/ipc";
import { useTranslation } from "../i18n";

// Plain answers to "what is this app, what are the web pages, how do sessions work".
const GUIDE_OPEN_KEY = "gsm.home.guideOpen";

const NUMPAD_KEYS: Array<{ key: string; labelKey: string }> = [
  { key: "Num0", labelKey: "home.guide.keyAi" },
  { key: "Num1", labelKey: "home.guide.keyOcrArea" },
  { key: "Num2", labelKey: "home.guide.keyOcrBox" },
  { key: "Num3", labelKey: "home.guide.keyAudio" },
  { key: "Num4", labelKey: "home.guide.keyTextFeed" },
  { key: "Num5", labelKey: "home.guide.keyOverlay" },
  { key: "Num6", labelKey: "home.guide.keyTranslate" },
  { key: "Num7", labelKey: "home.guide.keyFurigana" },
  { key: "Num8", labelKey: "home.guide.keySession" },
  { key: "Num9", labelKey: "home.guide.keyPause" },
  { key: "Num/", labelKey: "home.guide.keyOverlaySettings" },
  { key: "Num*", labelKey: "home.guide.keyYomitanSettings" },
  { key: "Num-", labelKey: "home.guide.keyLiveStats" },
];

export const GSM_WEB_PAGES: Array<{ path: string; labelKey: string; descriptionKey: string }> = [
  { path: "/texthooker", labelKey: "home.guide.pageTexthooker", descriptionKey: "home.guide.pageTexthookerDescription" },
  { path: "/review", labelKey: "home.guide.pageReview", descriptionKey: "home.guide.pageReviewDescription" },
  { path: "/stats", labelKey: "home.guide.pageStats", descriptionKey: "home.guide.pageStatsDescription" },
  { path: "/setup-check", labelKey: "home.guide.pageSetup", descriptionKey: "home.guide.pageSetupDescription" },
];

function readGuideOpen(): boolean {
  try {
    return window.localStorage.getItem(GUIDE_OPEN_KEY) !== "false";
  } catch {
    return true;
  }
}

export function HowGsmWorks() {
  const t = useTranslation();
  const [open, setOpen] = useState(readGuideOpen);

  const onToggle = useCallback((event: SyntheticEvent<HTMLDetailsElement>) => {
    const next = event.currentTarget.open;
    setOpen(next);
    try {
      window.localStorage.setItem(GUIDE_OPEN_KEY, String(next));
    } catch {
      // Only a convenience; the card still works without storage.
    }
  }, []);

  const openPage = useCallback((path: string) => void invokeIpc("openGsmWebPage", path), []);

  return (
    <details className="card home-guide-card" open={open} onToggle={onToggle}>
      <summary className="card-header">{t("home.guide.title")}</summary>
      <div className="card-body home-guide">
        <p className="home-guide__intro">{t("home.guide.intro")}</p>
        <div className="home-guide__grid">
          <section>
            <h4>{t("home.guide.appTitle")}</h4>
            <p>{t("home.guide.appBody")}</p>
          </section>
          <section>
            <h4>{t("home.guide.gameTitle")}</h4>
            <p>{t("home.guide.gameBody")}</p>
            <ul className="home-guide__keys">
              {NUMPAD_KEYS.map((entry) => (
                <li key={entry.key}>
                  <kbd>{entry.key}</kbd>
                  <span>{t(entry.labelKey)}</span>
                </li>
              ))}
            </ul>
            <p className="home-guide__note">{t("home.guide.keysNote")}</p>
          </section>
          <section>
            <h4>{t("home.guide.browserTitle")}</h4>
            <p>{t("home.guide.browserBody")}</p>
            <ul className="home-guide__pages">
              {GSM_WEB_PAGES.map((page) => (
                <li key={page.path}>
                  <button type="button" className="home-quick-btn" onClick={() => openPage(page.path)}>
                    {t(page.labelKey)}
                  </button>
                  <span>{t(page.descriptionKey)}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <section>
          <h4>{t("captureWizard.kind.explainTitle")}</h4>
          <p>{t("captureWizard.kind.explainHook")}</p>
          <p>{t("captureWizard.kind.explainOcr")}</p>
          <p>{t("captureWizard.kind.explainBoth")}</p>
        </section>
        <section>
          <h4>{t("home.guide.sessionsTitle")}</h4>
          <ul className="home-guide__list">
            <li>{t("home.guide.sessionsAuto")}</li>
            <li>{t("home.guide.sessionsManual")}</li>
            <li>{t("home.guide.sessionsHow")}</li>
            <li>{t("home.guide.sessionsReview")}</li>
          </ul>
        </section>
      </div>
    </details>
  );
}

export default HowGsmWorks;
