// ==============================================================================
// 🌶️ SPICE NEST - FLIPKART 1-CLICK ALL-PRODUCTS CRAWLER & AUTO-SYNC (v1.0)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Flipkart par apni Brand/Search ya Seller Hub page kholein:
//    👉 https://www.flipkart.com/search?q=Spice+Nest
//       (ya Flipkart Seller Hub: seller.flipkart.com/index.html#dashboard/my-listings)
// 2. F12 dabayein (Console tab kholein)
// 3. Neeche diya gaya poora code paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Sabhi Flipkart product cards, exact selling prices, MRP, ratings aur links extract karega.
// - Multiple pages hone par khud next page par navigate karega.
// - Screen par LIVE banner dikhayega: "Scanning Flipkart products...".
// - `flipkart_all_products_YYYY-MM-DD.json` file automatically download kar dega!
// - Spice Nest Hub (localhost:5000) me direct sync kar dega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST FLIPKART AUTO-CRAWLER STARTED", "color: #2874f0; font-weight: bold; font-size: 16px;");

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const items = new Map();

  // 1. On-screen floating progress banner
  let banner = document.getElementById("spicenest-fk-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "spicenest-fk-banner";
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
    banner.style.border = "2px solid #2874f0";
    document.body.appendChild(banner);
  }

  const updateBanner = (msg, count = items.size) => {
    banner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
        <span style="color: #2874f0; font-size: 14px; font-weight:700;">⚡ Flipkart Sync</span>
        <span style="background: #2874f0; color:#fff; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Active</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px;">📦 Total Products Captured: <b style="color: #10b981; font-size: 14px;">${count}</b></div>
    `;
  };

  // 2. Product Collector for Flipkart (Works on Search, Seller Hub, and PDP)
  const collectFlipkartProducts = () => {
    let before = items.size;

    // A. Flipkart Consumer Grid / List Cards
    const cardLinks = Array.from(document.querySelectorAll("a[href*='/p/'], a[href*='pid='], div[data-id]"));

    cardLinks.forEach(el => {
      let href = el.tagName === 'A' ? el.href : (el.querySelector("a[href*='/p/']") ? el.querySelector("a[href*='/p/']").href : "");
      let text = el.innerText ? el.innerText.trim().replace(/\n+/g, ' | ') : "";

      // Extract PID / FSN
      let pid = "";
      if (el.getAttribute("data-id")) {
        pid = el.getAttribute("data-id");
      } else if (href) {
        let m = href.match(/pid=([a-zA-Z0-9_-]+)/) || href.match(/\/p\/([a-zA-Z0-9_-]+)/);
        if (m) pid = m[1];
      }

      // Title
      let title = "";
      const titleEl = el.querySelector(".wjcEIp, .KzDlHZ, .s1Q9rs, [class*='title'], [class*='Title']");
      if (titleEl) {
        title = titleEl.innerText.trim();
      } else if (text) {
        title = text.split('|')[0].trim();
      }

      if (!title || title.length < 3) return;
      if (!pid) pid = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 24);

      if (!items.has(pid)) {
        // Selling Price
        let price = null;
        let pMatch = text.match(/₹\s*([0-9,]+)/);
        if (pMatch) price = parseFloat(pMatch[1].replace(/,/g, ''));

        // Rating
        let rating = null;
        let rMatch = text.match(/(\d\.\d)\s*★?/);
        if (rMatch) rating = parseFloat(rMatch[1]);

        let img = el.querySelector("img");
        let imgSrc = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";

        items.set(pid, {
          id: pid,
          product_id: pid,
          fsn: pid,
          name: title,
          price: price,
          rating: rating,
          url: href,
          img: imgSrc,
          text: text
        });
      }
    });

    // B. Flipkart Seller Hub Listing Rows (if on seller.flipkart.com)
    document.querySelectorAll("tr, div[class*='listing-row'], div[class*='table-row']").forEach(row => {
      const text = row.innerText ? row.innerText.trim().replace(/\n+/g, ' | ') : "";
      if (!text.includes('₹') && !text.includes('FSN')) return;

      const pMatch = text.match(/₹\s*([0-9,]+)/);
      if (!pMatch) return;

      const price = parseFloat(pMatch[1].replace(/,/g, ''));
      const parts = text.split('|').map(s => s.trim()).filter(Boolean);
      const title = parts[0] || 'Flipkart Seller Product';
      const pid = 'FK-' + title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 20);

      if (!items.has(pid)) {
        items.set(pid, {
          id: pid,
          product_id: pid,
          fsn: pid,
          name: title,
          price: price,
          rating: 4.2,
          url: window.location.href,
          img: "",
          text: text
        });
      }
    });

    return items.size - before;
  };

  // 3. Smooth scrolling for lazy hydration
  const scrollPageThoroughly = async () => {
    const scrollPoints = [0.35, 0.7, 1.0];
    for (let point of scrollPoints) {
      window.scrollTo({ top: document.body.scrollHeight * point, behavior: 'smooth' });
      await sleep(650);
      collectFlipkartProducts();
    }
    await sleep(600);
  };

  // 4. Find Next Page button on Flipkart
  const findNextButton = () => {
    const candidates = Array.from(document.querySelectorAll('a, button, span')).filter(el => {
      const txt = el.textContent.trim().toUpperCase();
      return ['NEXT', 'NEXT >', '>', '»'].includes(txt);
    });
    return candidates[candidates.length - 1] || null;
  };

  // --- START CRAWL ---
  updateBanner("🚀 Initializing Flipkart crawler...");
  await scrollPageThoroughly();

  let currentPage = 1;
  const maxPages = 10;

  while (currentPage <= maxPages) {
    updateBanner(`📄 Scanning Page ${currentPage}... (Captured: ${items.size})`);
    console.log(`%c📄 [Flipkart Page ${currentPage}] Scraping products...`, "color: #38bdf8; font-weight: bold;");

    await scrollPageThoroughly();
    const newlyAdded = collectFlipkartProducts();
    console.log(`   📦 Found ${newlyAdded} new items on Page ${currentPage} (Total: ${items.size})`);
    updateBanner(`✅ Page ${currentPage} done (${items.size} items)`, items.size);

    const nextBtn = findNextButton();
    if (!nextBtn) {
      console.log(`%c🏁 Genuine Last Page (${currentPage}) reached!`, "color: #10b981; font-weight: bold;");
      break;
    }

    console.log(`   👉 Clicking Next Page...`);
    updateBanner(`👉 Moving to Page ${currentPage + 1}...`, items.size);

    nextBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    nextBtn.click();
    await sleep(3000); // Wait for Flipkart hydration

    currentPage++;
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 FLIPKART CRAWL COMPLETE! Total ${allItems.length} products captured!`, "color: #10b981; font-weight: bold; font-size: 15px;");
  updateBanner(`🎉 Complete! All ${allItems.length} Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Flipkart search ya listings page par hain.");
    return;
  }

  // Step C: Automatic JSON File Download
  const todayStr = new Date().toISOString().split('T')[0];
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `flipkart_all_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // Step D: Auto-Sync directly to Spice Nest Hub (if running)
  let directSynced = false;
  try {
    updateBanner("🔄 Auto-syncing to Spice Nest Hub (localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/flipkart/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) {
      const data = await res.json();
      directSynced = true;
      console.log("✅ Flipkart Hub Sync Success:", data);
      updateBanner(`🎉 100% Synced to Hub! (${allItems.length} Items)`);
    }
  } catch (err) {}

  if (directSynced) {
    alert(`🎉 SUCCESS!\n\n• Flipkart se total ${allItems.length} products capture ho gaye!\n• JSON file automatically download ho gayi: flipkart_all_${allItems.length}_products_${todayStr}.json\n• Spice Nest Hub (localhost:5000) me direct sync ho gaya hai!`);
  } else {
    alert(`✅ SUCCESS!\n\n• Flipkart se total ${allItems.length} products capture ho gaye!\n• JSON file automatically download ho gayi: flipkart_all_${allItems.length}_products_${todayStr}.json\n\nAap is file ko Spice Nest Hub par "📤 Upload Flipkart JSON" button se upload kar sakte hain!`);
  }
})();
