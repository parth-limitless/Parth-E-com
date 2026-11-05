// ==============================================================================
// 🌶️ SPICE NEST - MEESHO 1-CLICK ALL-PAGES AUTO-CRAWLER & JSON EXPORTER (v3.0)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Meesho par apni STORE / CATALOG page kholein:
//    👉 https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2
//    (DHYAN DEIN: Cart page ya checkout page par nahi chalana hai, sirf Store page par!)
// 2. F12 dabayein (Console tab kholein)
// 3. Neeche diya gaya code paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Header ya Cart icon ko KABHI touch nahi karega (Strict Bottom Pagination).
// - Chahe aap kisi bhi page par ho, ye Page 1 se shuru karke Page 5 tak sabhi pages crawl karega.
// - Saare ~51 products capture karke JSON file automatically download kar dega!
// - Agar local Hub (localhost:5000) open hai to direct sync bhi kar dega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST MEESHO AUTO-CRAWLER (v3.0) STARTED", "color: #9f2089; font-weight: bold; font-size: 16px;");

  const STORE_URL = "https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2";

  // 1. URL Safety Check: User ko confirm karein ki wo Storefront page par hain
  if (!window.location.href.toLowerCase().includes("spicenestimpexprivatelimited")) {
    const proceed = confirm(
      "⚠️ DHYAN DEIN!\n\nAap abhi Meesho Storefront page par nahi hain (shayad Cart ya PDP page par hain).\n\nKya aap Spice Nest Storefront page par jana chahte hain?\n(OK dabane par Storefront page khul jayega)"
    );
    if (proceed) {
      window.location.href = STORE_URL;
    }
    return;
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const items = new Map();

  // 2. On-screen floating progress banner
  let banner = document.getElementById("spicenest-crawler-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "spicenest-crawler-banner";
    banner.style.position = "fixed";
    banner.style.top = "15px";
    banner.style.right = "15px";
    banner.style.zIndex = "9999999";
    banner.style.backgroundColor = "#0f172a";
    banner.style.color = "#ffffff";
    banner.style.padding = "14px 20px";
    banner.style.borderRadius = "12px";
    banner.style.boxShadow = "0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.4)";
    banner.style.fontFamily = "system-ui, -apple-system, sans-serif";
    banner.style.fontSize = "13px";
    banner.style.fontWeight = "600";
    banner.style.lineHeight = "1.5";
    banner.style.minWidth = "290px";
    banner.style.border = "2px solid #9f2089";
    document.body.appendChild(banner);
  }

  const updateBanner = (msg, count = items.size) => {
    banner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <span style="color: #f43f5e; font-size: 14px; font-weight:700;">🌶️ Spice Nest Hub</span>
        <span style="background: #9f2089; color:#fff; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Active</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px;">📦 Total Products: <b style="color: #10b981; font-size: 13px;">${count}</b></div>
    `;
  };

  // 3. Product collector
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

  // 4. Smooth scrolling to hydrate lazy-load products & images
  const scrollPageThoroughly = async () => {
    const scrollPoints = [0.35, 0.7, 1.0];
    for (let point of scrollPoints) {
      window.scrollTo({ top: document.body.scrollHeight * point, behavior: 'smooth' });
      await sleep(650);
      collectCurrentPage();
    }
    await sleep(600);
  };

  // 5. Safe Clicker (React 18 + Pointer/Mouse Events)
  const safeClick = (el) => {
    if (!el) return false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const target = el.closest('button, a, div') || el;

    const opts = { bubbles: true, cancelable: true, view: window };
    target.dispatchEvent(new PointerEvent('pointerdown', opts));
    target.dispatchEvent(new MouseEvent('mousedown', opts));
    target.dispatchEvent(new PointerEvent('pointerup', opts));
    target.dispatchEvent(new MouseEvent('mouseup', opts));
    target.dispatchEvent(new MouseEvent('click', opts));
    if (typeof target.click === 'function') {
      try { target.click(); } catch (e) {}
    }
    return true;
  };

  // 6. Strict Pagination Container Finder (Excludes header & top area completely)
  const getPaginationContainer = () => {
    const candidates = Array.from(document.querySelectorAll('div, nav, section')).filter(el => {
      const rect = el.getBoundingClientRect();
      // MUST be in lower section (never header/cart!)
      if (rect.top < 250) return false;
      const txt = el.innerText || '';
      if (txt.length > 250) return false; // tight row only
      const hasNav = /PREVIOUS|NEXT/i.test(txt);
      const hasNums = /\b1\b/.test(txt) && /\b[2-5]\b/.test(txt);
      return hasNav || hasNums;
    });

    candidates.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return candidates[0] || null;
  };

  // 7. Find exact page number element strictly at the bottom
  const findPageElement = (num) => {
    const numStr = String(num);
    const container = getPaginationContainer();
    const searchRoot = container || document.body;

    const leafs = Array.from(searchRoot.querySelectorAll('button, a, span, p, div')).filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.top < 250) return false; // Safety: Never touch header
      if (el.children.length > 0) return false; // Leaf element only
      return el.textContent.trim() === numStr;
    });

    if (leafs.length === 0) return null;
    leafs.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return leafs[0];
  };

  // 8. Find NEXT button
  const findNextButton = () => {
    const container = getPaginationContainer();
    const searchRoot = container || document.body;

    const leafs = Array.from(searchRoot.querySelectorAll('button, a, span, p, div')).filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.top < 250) return false;
      const txt = el.textContent.trim().toUpperCase();
      return ['NEXT', '>', '»', 'NEXT PAGE'].includes(txt);
    });

    if (leafs.length === 0) return null;
    leafs.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return leafs[0];
  };

  // 9. Detect total pages available (e.g. 5)
  const detectTotalPages = () => {
    const container = getPaginationContainer();
    const searchRoot = container || document.body;

    const leafs = Array.from(searchRoot.querySelectorAll('button, a, span, p, div')).filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.top < 250) return false;
      if (el.children.length > 0) return false;
      const txt = el.textContent.trim();
      return /^\d+$/.test(txt) && parseInt(txt, 10) >= 1 && parseInt(txt, 10) <= 20;
    });

    const nums = leafs.map(el => parseInt(el.textContent.trim(), 10));
    return nums.length > 0 ? Math.max(...nums) : 5;
  };

  // --- EXECUTION START ---
  updateBanner("🚀 Initializing Meesho Store Scraper...");
  await scrollPageThoroughly();

  const totalPages = detectTotalPages();
  console.log(`%c📊 Total Pages Detected: ${totalPages}`, "color: #38bdf8; font-weight: bold;");

  // Step A: Reset to Page 1 if currently on a later page
  const p1 = findPageElement(1);
  if (p1) {
    const isP1Selected = window.getComputedStyle(p1).color.includes("255") ||
                         window.getComputedStyle(p1.parentElement || p1).backgroundColor.includes("rgb(159");
    if (!isP1Selected) {
      updateBanner("⏪ Resetting to Page 1 first...");
      safeClick(p1);
      await sleep(2500);
      window.scrollTo(0, 0);
      await sleep(500);
    }
  }

  // Step B: Sequentially scrape Page 1 to totalPages
  for (let p = 1; p <= totalPages; p++) {
    updateBanner(`📄 Scanning Page ${p} of ${totalPages}...`);
    console.log(`%c📄 [Page ${p}/${totalPages}] Scrolling and scraping products...`, "color: #38bdf8; font-weight: bold;");

    await scrollPageThoroughly();
    const newItems = collectCurrentPage();
    console.log(`   📦 Found ${newItems} new items (Total captured: ${items.size})`);
    updateBanner(`✅ Page ${p} done!`, items.size);

    if (p < totalPages) {
      const nextPage = p + 1;
      updateBanner(`👉 Moving to Page ${nextPage}...`);
      console.log(`   👉 Clicking Page ${nextPage}...`);

      let nextTarget = findPageElement(nextPage);
      if (!nextTarget) {
        nextTarget = findNextButton();
      }

      if (nextTarget) {
        safeClick(nextTarget);
        await sleep(2600); // Wait for Meesho React hydration
      } else {
        console.warn(`⚠️ Page ${nextPage} button nahi mila, scrolling to check...`);
        await sleep(1500);
      }
    }
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 SCRAPING COMPLETE! Total ${allItems.length} products captured!`, "color: #10b981; font-weight: bold; font-size: 15px;");
  updateBanner(`🎉 Complete! ${allItems.length} Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Spice Nest Storefront page par hain.");
    return;
  }

  // Step C: Automatic JSON File Download
  const todayStr = new Date().toISOString().split('T')[0];
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `meesho_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // Step D: Auto-Sync to Local Hub (if running)
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
    }
  } catch (err) {}

  // Final Notification
  if (directSynced) {
    alert(`🎉 SUCCESS!\n\n• Meesho ke sabhi ${totalPages} pages se total ${allItems.length} products extract ho gaye!\n• JSON file automatically download ho gayi hai: meesho_${allItems.length}_products_${todayStr}.json\n• Spice Nest Hub (localhost:5000) me direct sync ho gaya hai!`);
  } else {
    alert(`✅ SUCCESS!\n\n• Meesho ke sabhi ${totalPages} pages se total ${allItems.length} products extract ho gaye!\n• JSON file automatically download ho gayi hai: meesho_${allItems.length}_products_${todayStr}.json\n\nAap is file ko Spice Nest Hub par "📤 Upload Meesho JSON" button se upload kar sakte hain!`);
  }
})();
