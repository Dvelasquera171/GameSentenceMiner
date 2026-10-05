// @vitest-environment jsdom

import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n";
import { GSM_WEB_PAGE_PATHS } from "../../../main/gsm_web_pages";
import { GSM_WEB_PAGES, HowGsmWorks } from "./HowGsmWorks";

const invokeMock = vi.fn();

describe("HowGsmWorks", () => {
  let container: HTMLDivElement;
  let root: Root;

  async function render() {
    await act(async () => {
      root.render(
        <I18nProvider>
          <HowGsmWorks />
        </I18nProvider>,
      );
    });
  }

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    invokeMock.mockReset();
    Object.defineProperty(window, "ipcRenderer", {
      configurable: true,
      value: { invoke: invokeMock, send: vi.fn(), on: () => () => {}, removeListener: () => {} },
    });
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("explains the app, the game, the browser pages and sessions", async () => {
    await render();
    const text = container.textContent ?? "";
    expect(text).toContain("How GSM works");
    expect(text).toContain("This app: set up and start");
    expect(text).toContain("In the game: read and look up");
    expect(text).toContain("In the browser: look back");
    expect(text).toContain("Hook or OCR?");
    expect(text).toContain("Reading sessions");
    expect(text).toContain("Num8");
    expect(container.querySelector("details")?.open).toBe(true);
  });

  it("opens GSM web pages through the restricted IPC", async () => {
    await render();
    const review = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Review");
    await act(async () => review!.click());
    expect(invokeMock).toHaveBeenCalledWith("openGsmWebPage", "/review");
  });

  it("only links pages the main process allows", () => {
    for (const page of GSM_WEB_PAGES) {
      expect(GSM_WEB_PAGE_PATHS.has(page.path)).toBe(true);
    }
  });

  it("remembers when the card is collapsed", async () => {
    window.localStorage.setItem("gsm.home.guideOpen", "false");
    await render();
    expect(container.querySelector("details")?.open).toBe(false);
  });
});
