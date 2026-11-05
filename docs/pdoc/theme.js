// SPDX-License-Identifier: LGPL-2.1-or-later
(() => {
    const key = "rexlib-metadata-theme";
    const system = matchMedia("(prefers-color-scheme: dark)");
    const stored = () => {
        try {
            return localStorage.getItem(key);
        } catch {
            return null;
        }
    };
    const chosen = () => stored() || (system.matches ? "dark" : "light");

    const pictures = (theme) => {
        for (const source of document.querySelectorAll("picture source[media]")) {
            source.dataset.media ??= source.media;
            const dark = source.dataset.media.includes("prefers-color-scheme: dark");
            source.media = dark && theme === "dark" ? "all" : dark ? "not all" : source.dataset.media;
        }
    };
    const apply = (theme) => {
        document.documentElement.dataset.theme = theme;
        pictures(theme);
    };

    apply(chosen());
    system.addEventListener("change", () => stored() || apply(chosen()));
    document.addEventListener("DOMContentLoaded", () => {
        apply(chosen());
        for (const button of document.querySelectorAll(".theme-toggle")) {
            button.addEventListener("click", () => {
                const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
                try {
                    localStorage.setItem(key, next);
                } catch {}
                apply(next);
            });
        }
    });
})();
