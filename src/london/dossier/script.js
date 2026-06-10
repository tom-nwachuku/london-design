      const storageKey = "london-workbench-route";
      function storageGet(key) {
        try { return window.localStorage.getItem(key); } catch { return null; }
      }
      function storageSet(key, value) {
        try { window.localStorage.setItem(key, value); } catch {}
      }
      const buttons = Array.from(document.querySelectorAll("[data-route-button]"));
      const panels = Array.from(document.querySelectorAll("[data-route-panel]"));
      const firstRoute = buttons[0]?.dataset.routeButton || "";
      const validRoutes = new Set(buttons.map((button) => button.dataset.routeButton).filter(Boolean));
      function selectRoute(routeId) {
        if (!routeId) return;
        buttons.forEach((button) => button.setAttribute("aria-selected", String(button.dataset.routeButton === routeId)));
        panels.forEach((panel) => { panel.hidden = panel.dataset.routePanel !== routeId; });
        storageSet(storageKey, routeId);
      }
      buttons.forEach((button) => button.addEventListener("click", () => selectRoute(button.dataset.routeButton)));
      const storedRoute = storageGet(storageKey);
      const initialRoute = validRoutes.has(storedRoute) ? storedRoute : firstRoute;
      selectRoute(initialRoute);

      window.londonVerifyFontPreviews = async function londonVerifyFontPreviews() {
        await document.fonts.ready;
        const genericFamilies = new Set(["serif", "sans-serif", "monospace", "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace"]);
        const rows = Array.from(document.querySelectorAll("[data-font-preview-status]")).map((node) => {
          const target = node.querySelector(".font-specimen, .route-specimen") || node;
          const expected = target.dataset.fontPreviewFamily || node.dataset.fontPreviewFamily || "";
          const status = target.dataset.fontPreviewStatus || node.dataset.fontPreviewStatus;
          const computed = window.getComputedStyle(target).fontFamily || "";
          const firstFamily = computed.split(",")[0]?.trim().replace(/^['"]|['"]$/g, "") || "";
          const cssFamily = expected.includes(" ") ? `"${expected.replace(/"/g, '\\"')}"` : expected;
          const checked = expected ? document.fonts.check(`16px ${cssFamily}`) : false;
          const loadedClaim = status === "actual_loaded" || status === "source_loaded";
          const ok = !loadedClaim || (computed.includes(expected) && checked && !genericFamilies.has(firstFamily));
          return { status, expected, computed, checked, ok };
        });
        const failures = rows.filter((row) => !row.ok);
        if (failures.length) throw new Error(`London font preview verification failed: ${JSON.stringify(failures)}`);
        return rows;
      };

      function showToast(message) {
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 1400);
      }
      async function copyText(text) {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const area = document.createElement("textarea");
          area.value = text;
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }
        showToast("Copied");
      }
      document.querySelectorAll("[data-copy]").forEach((button) => {
        button.addEventListener("click", () => copyText(button.dataset.copy || ""));
      });

      const persistPrefix = document.body?.dataset.persistPrefix || "global";
      document.querySelectorAll("details[data-persist]").forEach((detail) => {
        const key = "london-detail-" + persistPrefix + "-" + detail.dataset.persist;
        detail.open = storageGet(key) === "open";
        detail.addEventListener("toggle", () => storageSet(key, detail.open ? "open" : "closed"));
      });

      // --- Shared nav surfaces (NAV-02..05), ported from prototype.py -----------
      // The ⌘K command palette + mobile drawer + left-rail scroll-spy. Vanilla,
      // inline, no remote assets. The scroll-spy is reconciled to ONE
      // IntersectionObserver that lights BOTH the sticky subnav links AND the
      // left-rail / palette [data-nav-link] entries + the route switcher tabs.
      const drawer = document.querySelector("[data-mobile-drawer]");
      const menuButton = document.querySelector("[data-mobile-toggle]");
      const palette = document.querySelector("[data-command-palette]");
      const commandInput = document.querySelector("[data-command-search]");
      const commandItems = Array.from(document.querySelectorAll("[data-command-item]"));
      const commandEmpty = document.querySelector("[data-command-empty]");
      const navLinks = Array.from(document.querySelectorAll("[data-nav-link]"));
      const routeTabs = Array.from(document.querySelectorAll("[data-nav-route-tab]"));

      const setDrawer = (open) => {
        if (!drawer || !menuButton) return;
        drawer.hidden = !open;
        menuButton.setAttribute("aria-expanded", String(open));
      };
      const openPalette = () => {
        if (!palette || !commandInput) return;
        palette.hidden = false;
        commandInput.focus();
        commandInput.select();
      };
      const closePalette = () => {
        if (!palette) return;
        palette.hidden = true;
      };

      menuButton?.addEventListener("click", () => setDrawer(drawer?.hidden));
      document.querySelector("[data-mobile-close]")?.addEventListener("click", () => setDrawer(false));
      document.querySelectorAll("[data-command-open]").forEach((trigger) => trigger.addEventListener("click", openPalette));
      document.querySelector("[data-command-close]")?.addEventListener("click", closePalette);
      palette?.addEventListener("click", (event) => {
        if (event.target === palette) closePalette();
      });
      commandInput?.addEventListener("input", () => {
        const query = commandInput.value.trim().toLowerCase();
        let visible = 0;
        commandItems.forEach((item) => {
          const match = query === "" || (item.dataset.commandKey || "").includes(query);
          item.hidden = !match;
          if (match) visible += 1;
        });
        if (commandEmpty) commandEmpty.hidden = visible !== 0;
      });
      navLinks.forEach((link) => {
        link.addEventListener("click", () => {
          const routeId = link.dataset.navRoute;
          if (routeId && validRoutes.has(routeId)) selectRoute(routeId);
          setDrawer(false);
          closePalette();
        });
      });

      // Scroll-spy: highlight the active subnav link AND the left-rail/palette nav
      // links AND the route switcher tab as sections enter the viewport. Degrades to
      // plain anchors if IntersectionObserver / JS is unavailable. ONE observer.
      const subnavLinks = Array.from(document.querySelectorAll(".subnav-link[data-nav-section]"));
      const navSections = Array.from(document.querySelectorAll("[data-nav-section][data-jump-target]"));
      const linkForSection = new Map(subnavLinks.map((link) => [link.dataset.navSection, link]));
      function setActiveSection(sectionId, routeId) {
        subnavLinks.forEach((link) => {
          const active = link.dataset.navSection === sectionId;
          link.classList.toggle("is-active", active);
          if (active) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        });
        navLinks.forEach((link) => {
          if (link.dataset.navLink === sectionId) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        });
        if (routeId) {
          routeTabs.forEach((tab) => {
            tab.setAttribute("aria-selected", String(tab.dataset.navRouteTab === routeId));
          });
        }
      }
      function visibleHashTarget() {
        if (!window.location.hash) return null;
        const target = document.getElementById(window.location.hash.slice(1));
        if (!target) return null;
        const rect = target.getBoundingClientRect();
        if (rect.top < window.innerHeight * 0.55 && rect.bottom > 120) return target;
        return null;
      }
      if ("IntersectionObserver" in window && navSections.length) {
        const spy = new IntersectionObserver((entries) => {
          const hashTarget = visibleHashTarget();
          if (hashTarget) {
            setActiveSection(hashTarget.id || hashTarget.dataset.navSection, hashTarget.dataset.navRoute);
            return;
          }
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .sort((a, b) => b.intersectionRatio - a.intersectionRatio || a.boundingClientRect.top - b.boundingClientRect.top)[0];
          if (!visible) return;
          const id = visible.target.id || visible.target.dataset.navSection;
          const routeId = visible.target.dataset.navRoute;
          setActiveSection(id, routeId);
        }, { rootMargin: "-88px 0px -60% 0px", threshold: [0, 0.08, 0.22, 0.45] });
        navSections.forEach((section) => spy.observe(section));
      }

      document.addEventListener("keydown", (event) => {
        const target = event.target;
        const isEditable = target?.matches?.("input, textarea, select, [contenteditable='true']");
        const key = event.key.toLowerCase();
        if ((event.metaKey || event.ctrlKey) && key === "k") {
          event.preventDefault();
          openPalette();
          return;
        }
        if (event.key === "/" && !isEditable && !event.metaKey && !event.ctrlKey && !event.altKey) {
          event.preventDefault();
          openPalette();
          return;
        }
        if (event.key === "Escape") {
          closePalette();
          setDrawer(false);
          closeLightbox();
        }
      });

      document.querySelectorAll('a[href^="#"]').forEach((link) => {
        link.addEventListener("click", () => {
          const target = document.querySelector(link.getAttribute("href"));
          if (!target) return;
          target.classList.add("is-target-flash");
          setTimeout(() => target.classList.remove("is-target-flash"), 900);
        });
      });

      const lightbox = document.querySelector("#lightbox");
      const lightboxImage = lightbox?.querySelector("img");
      const lightboxCaption = lightbox?.querySelector("figcaption");
      const lightboxClose = lightbox?.querySelector(".lightbox-close");
      function closeLightbox() {
        if (!lightbox) return;
        lightbox.hidden = true;
        lightbox.setAttribute("aria-hidden", "true");
      }
      document.querySelectorAll("[data-lightbox-src]").forEach((button) => {
        button.addEventListener("click", () => {
          if (!lightbox || !lightboxImage || !lightboxCaption) return;
          lightboxImage.src = button.dataset.lightboxSrc || "";
          lightboxCaption.textContent = button.dataset.lightboxTitle || "System sketch";
          lightbox.hidden = false;
          lightbox.setAttribute("aria-hidden", "false");
          lightboxClose?.focus();
        });
      });
      lightbox?.addEventListener("click", (event) => {
        if (event.target === lightbox) closeLightbox();
      });
      lightboxClose?.addEventListener("click", closeLightbox);

      if ("scrollRestoration" in history) history.scrollRestoration = "manual";
      const scrollToHashTarget = () => {
        if (!window.location.hash) return false;
        const target = document.getElementById(window.location.hash.slice(1));
        if (!target) return false;
        const alignTarget = () => {
          target.scrollIntoView({ block: "start" });
          setActiveSection(target.id || target.dataset.navSection, target.dataset.navRoute);
        };
        requestAnimationFrame(alignTarget);
        setTimeout(alignTarget, 80);
        setTimeout(alignTarget, 260);
        setTimeout(alignTarget, 900);
        setTimeout(alignTarget, 1800);
        return true;
      };
      window.addEventListener("beforeunload", () => storageSet("london-scroll-y", String(window.scrollY)));
      window.addEventListener("load", () => {
        if (scrollToHashTarget()) return;
        const y = Number(storageGet("london-scroll-y") || 0);
        if (y > 0) setTimeout(() => window.scrollTo(0, y), 0);
      });
      window.addEventListener("hashchange", scrollToHashTarget);
      window.addEventListener("beforeprint", () => document.querySelectorAll("details").forEach((detail) => { detail.open = true; }));
