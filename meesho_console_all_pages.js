// ==============================================================================
// 🌶️ SPICE NEST - MEESHO ALL 86+ PRODUCTS COMPLETE STORE CRAWLER (v4.0)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Meesho par apni Storefront page kholein:
//    👉 https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2
// 2. F12 dabayein (Console tab kholein)
// 3. Neeche diya gaya poora code paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Page 5 par ruke bina, aage ke Page 6, 7, 8, 9, 10... sabhi pages par jayega.
// - Jab tak store ke saare 86 products capture nahi ho jate, tab tak automatic NEXT karega.
// - Screen par LIVE banner me dikhayega: "Page 6... Total 60 Products", "Page 8... Total 86 Products".
// - Khatam hote hi `meesho_all_86_products_YYYY-MM-DD.json` file download kar dega!
// - Local Hub (localhost:5000) me direct sync kar dega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST MEESHO 86+ PRODUCTS FULL CRAWLER STARTED", "color: #9f2089; font-weight: bold; font-size: 16px;");

  const STORE_URL = "https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2";

  // 1. Safety Check: Verify user is on the Storefront page
  if (!window.location.href.toLowerCase().includes("spicenestimpexprivatelimited")) {
    const proceed = confirm(
      "⚠️ DHYAN DEIN!\n\nAap abhi Meesho Storefront page par nahi hain.\n\nKya aap Spice Nest Storefront page par jana chahte hain?\n(OK dabane par Storefront page khul jayega)"
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
    banner.style.boxShadow = "0 10px 25px -5px rgba(0, 0, 0, 0.5)";
    banner.style.fontFamily = "system-ui, -apple-system, sans-serif";
    banner.style.fontSize = "13px";
    banner.style.fontWeight = "600";
    banner.style.lineHeight = "1.5";
    banner.style.minWidth = "300px";
    banner.style.border = "2px solid #9f2089";
    document.body.appendChild(banner);
  }

  const updateBanner = (msg, count = items.size) => {
    banner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <span style="color: #f43f5e; font-size: 14px; font-weight:700;">🌶️ Spice Nest Hub</span>
        <span style="background: #9f2089; color:#fff; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Full Store Crawl</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px;">📦 Total Products Captured: <b style="color: #10b981; font-size: 14px;">${count}</b></div>
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

  // 4. Smooth scrolling for lazy-loaded products
  const scrollPageThoroughly = async () => {
    const scrollPoints = [0.35, 0.7, 1.0];
    for (let point of scrollPoints) {
      window.scrollTo({ top: document.body.scrollHeight * point, behavior: 'smooth' });
      await sleep(650);
      collectCurrentPage();
    }
    await sleep(600);
  };

  // 5. Safe Clicker (React 18 Pointer/Mouse Events)
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

  // 6. Resilient Bottom Pagination Locator (Strictly excludes header & cart)
  const findBottomElement = (predicate) => {
    const allLeafs = Array.from(document.querySelectorAll('button, a, span, p, div')).filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.top < 200) return false; // Never touch header/cart
      if (el.children.length > 1) return false; // Leaf element
      if (rect.width === 0 || rect.height === 0) return false;
      return predicate(el.textContent.trim(), el);
    });

    if (allLeafs.length === 0) return null;
    allLeafs.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return allLeafs[0];
  };

  const findPageElement = (num) => {
    const numStr = String(num);
    return findBottomElement(txt => txt === numStr);
  };

  const findNextButton = () => {
    return findBottomElement(txt => {
      const upper = txt.toUpperCase();
      return upper === 'NEXT' || upper === '>' || upper === '»' || upper === 'NEXT PAGE';
    });
  };

  // --- START CRAWL PROCESS ---
  updateBanner("🚀 Initializing complete store crawler...");
  await scrollPageThoroughly();

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

  // Step B: Loop through ALL pages (1 to 25) until genuine end
  let currentPage = 1;
  const maxSafetyPages = 25;
  let reachedEnd = false;

  while (currentPage <= maxSafetyPages && !reachedEnd) {
    updateBanner(`📄 Scanning Page ${currentPage}... (Captured: ${items.size})`);
    console.log(`%c📄 [Page ${currentPage}] Scanning products...`, "color: #38bdf8; font-weight: bold;");

    await scrollPageThoroughly();
    const newItems = collectCurrentPage();
    console.log(`   📦 Found ${newItems} new items on Page ${currentPage} (Total captured: ${items.size})`);
    updateBanner(`✅ Page ${currentPage} complete (${items.size} items)`, items.size);

    const nextPageNum = currentPage + 1;

    // Look for next page button: First by number, then by 'NEXT' label
    let nextBtn = findPageElement(nextPageNum);
    let usedNextLabel = false;

    if (!nextBtn) {
      nextBtn = findNextButton();
      usedNextLabel = true;
    }

    // Double check bottom scroll if not found
    if (!nextBtn) {
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
      await sleep(800);
      nextBtn = findPageElement(nextPageNum) || findNextButton();
    }

    // Genuine end reached if no next button exists
    if (!nextBtn) {
      console.log(`%c🏁 Genuine Last Page (${currentPage}) reached! Total ${items.size} products captured!`, "color: #10b981; font-weight: bold;");
      reachedEnd = true;
      break;
    }

    console.log(`   👉 Clicking Page ${nextPageNum}${usedNextLabel ? ' (via NEXT button)' : ''}...`);
    updateBanner(`👉 Moving to Page ${nextPageNum}...`, items.size);

    safeClick(nextBtn);
    await sleep(2800); // Wait for Meesho React hydration

    currentPage++;
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 SCRAPING COMPLETE! Total ${allItems.length} products captured across ${currentPage} pages!`, "color: #10b981; font-weight: bold; font-size: 15px;");
  updateBanner(`🎉 Complete! All ${allItems.length} Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya Storefront page par check karein.");
    return;
  }

  // Step C: Automatic JSON File Download
  const todayStr = new Date().toISOString().split('T')[0];
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `meesho_all_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // Step D: Auto-Sync to Hub (if running)
  let directSynced = false;
  try {
    updateBanner("🔄 Auto-syncing to Spice Nest Hub (localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/meesho/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) {
      directSynced = true;
      updateBanner(`🎉 100% Synced to Hub! (${allItems.length} Items)`);
    }
  } catch (err) {}

  if (directSynced) {
    alert(`🎉 SUCCESS!\n\n• Meesho ke sabhi ${currentPage} pages se total ${allItems.length} products capture ho gaye!\n• JSON file automatically download ho gayi: meesho_all_${allItems.length}_products_${todayStr}.json\n• Spice Nest Hub (localhost:5000) me direct sync ho gaya hai!`);
  } else {
    alert(`✅ SUCCESS!\n\n• Meesho ke sabhi ${currentPage} pages se total ${allItems.length} products capture ho gaye!\n• JSON file automatically download ho gayi: meesho_all_${allItems.length}_products_${todayStr}.json\n\nAap is file ko Spice Nest Hub par "📤 Upload Meesho JSON" button se upload kar sakte hain!`);
  }
})();
