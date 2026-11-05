// ==============================================================================
// 🌶️ SPICE NEST - MEESHO 1-CLICK ALL-PAGES AUTO-CRAWLER & DIRECT SYNC (v2.0)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Meesho par apni store / catalog page kholein:
//    https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2
// 2. F12 dabayein (ya Right Click -> Inspect -> Console tab)
// 3. Neeche diya gaya poora code Console me paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Chahe aap Page 5 par ho ya Page 1 par, ye automatically Page 1 se shuru karega.
// - Page 1 -> 2 -> 3 -> 4 -> 5 har page par khud click karega.
// - Har page ko scroll karke saare products & exact prices collect karega.
// - Screen par LIVE banner dikhayega ki kaunsa page scan ho raha hai.
// - Sabhi 51 products ko seedhe aapke Spice Nest Hub (http://localhost:5000) me sync karega!
// - Ek backup JSON file bhi automatically download kar dega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST MEESHO AUTO-SCRAPER STARTED", "color: #9f2089; font-weight: bold; font-size: 16px;");

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const items = new Map();

  // 1. Create a stylish floating status widget on screen
  let banner = document.getElementById("spicenest-crawler-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "spicenest-crawler-banner";
    banner.style.position = "fixed";
    banner.style.top = "15px";
    banner.style.right = "15px";
    banner.style.zIndex = "999999";
    banner.style.backgroundColor = "#1e293b";
    banner.style.color = "#ffffff";
    banner.style.padding = "14px 20px";
    banner.style.borderRadius = "12px";
    banner.style.boxShadow = "0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.3)";
    banner.style.fontFamily = "system-ui, -apple-system, sans-serif";
    banner.style.fontSize = "13px";
    banner.style.fontWeight = "600";
    banner.style.lineHeight = "1.5";
    banner.style.minWidth = "280px";
    banner.style.border = "2px solid #9f2089";
    document.body.appendChild(banner);
  }

  const updateBanner = (msg, count = items.size) => {
    banner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <span style="color: #f43f5e; font-size: 14px;">🌶️ Spice Nest Hub</span>
        <span style="background: #9f2089; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Active</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px;">📦 Total Products Captured: <b style="color: #10b981; font-size: 13px;">${count}</b></div>
    `;
  };

  // 2. Collect products from current DOM
  const collectCurrentPage = () => {
    let before = items.size;
    document.querySelectorAll("a[href*='/p/']").forEach(a => {
      let m = a.href.match(/\/p\/([a-zA-Z0-9_-]+)/);
      if (m && !items.has(m[1])) {
        const pid = m[1];
        const cardText = a.innerText.trim().replace(/\n+/g, ' | ');
        const img = a.querySelector("img");
        const imgSrc = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";

        items.set(pid, {
          id: pid,
          product_id: pid,
          url: a.href,
          text: cardText,
          img: imgSrc
        });
      }
    });
    return items.size - before;
  };

  // 3. Smooth scroll to hydrate lazy images and cards
  const scrollPageThoroughly = async () => {
    const scrollPoints = [0.3, 0.65, 1.0];
    for (let point of scrollPoints) {
      window.scrollTo({ top: document.body.scrollHeight * point, behavior: 'smooth' });
      await sleep(650);
      collectCurrentPage();
    }
    await sleep(600);
  };

  // 4. Bulletproof Clicker for React 18 & Styled Components
  const triggerClick = (el) => {
    if (!el) return false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const targets = [el, el.parentElement, el.closest('button, a, div')].filter(Boolean);

    for (const t of targets) {
      const opts = { bubbles: true, cancelable: true, view: window };
      t.dispatchEvent(new PointerEvent('pointerdown', opts));
      t.dispatchEvent(new MouseEvent('mousedown', opts));
      t.dispatchEvent(new PointerEvent('pointerup', opts));
      t.dispatchEvent(new MouseEvent('mouseup', opts));
      t.dispatchEvent(new MouseEvent('click', opts));
      if (typeof t.click === 'function') {
        try { t.click(); } catch (e) {}
      }
    }
    return true;
  };

  // 5. Find a specific page button in the pagination area
  const findPageElement = (num) => {
    const numStr = String(num);
    const candidates = Array.from(document.querySelectorAll('button, a, span, p, div')).filter(el => {
      if (el.children.length > 0) return false; // leaf element
      if (el.textContent.trim() !== numStr) return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });

    if (candidates.length === 0) return null;

    // Filter for elements located in the bottom 40% of the document or near PREVIOUS/NEXT
    candidates.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return candidates[0];
  };

  // 6. Find NEXT button
  const findNextButton = () => {
    const candidates = Array.from(document.querySelectorAll('button, a, span, p, div')).filter(el => {
      const txt = el.textContent.trim().toUpperCase();
      if (['NEXT', '>', '»', 'NEXT PAGE'].includes(txt)) {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }
      return false;
    });
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return candidates[0];
  };

  // 7. Detect total available pages (e.g. 5)
  const detectAvailablePages = () => {
    const allLeafs = Array.from(document.querySelectorAll('button, a, span, p, div')).filter(el => {
      if (el.children.length > 0) return false;
      const txt = el.textContent.trim();
      return /^\d+$/.test(txt) && parseInt(txt, 10) >= 1 && parseInt(txt, 10) <= 20;
    });

    const pageNumbers = allLeafs.map(el => parseInt(el.textContent.trim(), 10));
    return pageNumbers.length > 0 ? Math.max(...pageNumbers) : 5;
  };

  updateBanner("🚀 Initializing scan...");
  await scrollPageThoroughly();

  const totalPages = detectAvailablePages();
  console.log(`%c📊 Detected ${totalPages} total pages in Meesho storefront.`, "color: #38bdf8; font-weight: bold;");

  // Step A: If user is on Page 2, 3, 4, 5, go back to Page 1 first!
  const page1Btn = findPageElement(1);
  if (page1Btn) {
    const p1Rect = page1Btn.getBoundingClientRect();
    const isP1Selected = window.getComputedStyle(page1Btn).color.includes("255") || 
                         window.getComputedStyle(page1Btn.parentElement || page1Btn).backgroundColor.includes("rgb(159");
    if (!isP1Selected) {
      updateBanner("⏪ Navigating to Page 1 to start fresh...");
      triggerClick(page1Btn);
      await sleep(2400);
      window.scrollTo(0, 0);
      await sleep(500);
    }
  }

  // Step B: Crawl sequentially from Page 1 to totalPages
  for (let p = 1; p <= totalPages; p++) {
    updateBanner(`📄 Scanning Page ${p} of ${totalPages}...`);
    console.log(`%c📄 [Page ${p}/${totalPages}] Scrolling and scraping...`, "color: #38bdf8; font-weight: bold;");

    await scrollPageThoroughly();
    const newItems = collectCurrentPage();
    console.log(`   📦 Found ${newItems} new items (Total captured: ${items.size})`);
    updateBanner(`✅ Page ${p} complete!`, items.size);

    if (p < totalPages) {
      const nextPage = p + 1;
      updateBanner(`👉 Moving to Page ${nextPage}...`);
      console.log(`   👉 Clicking Page ${nextPage}...`);

      let nextTarget = findPageElement(nextPage);
      if (!nextTarget) {
        nextTarget = findNextButton();
      }

      if (nextTarget) {
        triggerClick(nextTarget);
        await sleep(2500); // Wait for Meesho React hydration
      } else {
        console.warn(`⚠️ Could not find button for Page ${nextPage}. Checking if more items load...`);
        await sleep(1500);
      }
    }
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 SCAN FINISHED! Total ${allItems.length} products captured across all pages!`, "color: #10b981; font-weight: bold; font-size: 15px;");
  updateBanner(`🎉 Complete! ${allItems.length} Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Meesho Storefront page par hain.");
    return;
  }

  // 1. Direct Local Hub Sync
  let directSynced = false;
  try {
    updateBanner("🔄 Auto-syncing to Spice Nest Hub (localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/meesho/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) {
      const data = await res.json();
      directSynced = true;
      console.log("✅ Hub Sync Success:", data);
      updateBanner(`🎉 100% Synced to Hub! (${allItems.length} Items)`);
      alert(`🎉 SUCCESS!\n\nMeesho ke sabhi ${totalPages} pages se ${allItems.length} products extract ho gaye hain aur direct Spice Nest Hub me SYNC ho gaye!\n\n• Total Products: ${allItems.length}\n• Status: Direct Sync Successful`);
    }
  } catch (err) {
    console.warn("⚠️ Direct Hub sync skipped (server offline or CORS). Downloading JSON backup...", err);
  }

  // 2. Download JSON File Backup
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const todayStr = new Date().toISOString().split('T')[0];
  a.download = `meesho_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  if (!directSynced) {
    updateBanner(`✅ Downloaded JSON (${allItems.length} Items)`);
    alert(`✅ Done!\n\nSabhi ${totalPages} pages se total ${allItems.length} products ki JSON file download ho gayi hai!\n\nAap is file ko Spice Nest Hub par "📤 Upload Meesho JSON" button se upload kar sakte hain.`);
  }
})();
