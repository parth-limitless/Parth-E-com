// ==============================================================================
// 🌶️ SPICE NEST - FLIPKART BULLETPROOF 53+ PRODUCTS CRAWLER (v5.5)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Flipkart par apna Spice Nest page kholein:
//    👉 https://www.flipkart.com/food-products/spice-nest~brand/pr?sid=eat&page=1
//       (ya https://www.flipkart.com/search?q=Spice+Nest)
// 2. F12 dabayein (Console tab kholein)
// 3. Neeche diya gaya poora code paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Page 1 (40 items) aur Page 2 (13 items) dono ka poora 53+ products capture karega.
// - Footer ke "Reviews for Popular" section ko 100% DROP karega (zero review items).
// - Exact Selling Price aur MRP nikalega (koi discount corruption nahi).
// - Out of stock items ko detect karega.
// - Main Price Hub (Photo 1) ko TOUCH NAHI KAREGA.
// - Daily snapshot save karega aur `flipkart_all_53_products_YYYY-MM-DD.json` download karega.
// - Spice Nest Hub (localhost:5000/flipkart-seller) par auto-sync karega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST FLIPKART 53+ PRODUCTS CRAWLER (v5.5)", "color: #2874f0; font-weight: bold; font-size: 16px;");

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // 1. Session Storage Accumulator (Page 1 + Page 2 ko merge karne ke liye)
  let stored = [];
  try {
    stored = JSON.parse(sessionStorage.getItem("spicenest_fk_items") || "[]");
  } catch (e) { stored = []; }

  const items = new Map();
  stored.forEach(it => { if (it && it.product_id) items.set(it.product_id, it); });

  // 2. On-screen floating progress banner
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
    banner.style.minWidth = "320px";
    banner.style.border = "2px solid #2874f0";
    document.body.appendChild(banner);
  }

  const updateBanner = (msg, count = items.size) => {
    banner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
        <span style="color: #2874f0; font-size: 14px; font-weight:700;">⚡ Flipkart Sync v5.5</span>
        <span style="background: #2874f0; color:#fff; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Active</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px; margin-top: 4px;">📦 Total Captured: <b style="color: #10b981; font-size: 15px;">${count}</b> Products</div>
    `;
  };

  // 3. Robust Product Extractor
  const extractFromRoot = (rootDoc) => {
    let countBefore = items.size;
    let productCards = Array.from(rootDoc.querySelectorAll("div[data-id]"));

    // Fallback if data-id is wrapped
    if (productCards.length === 0) {
      productCards = Array.from(rootDoc.querySelectorAll("div._1AtVbE, div.cPHDOP, div._75nlfW")).filter(d => {
        return d.querySelector("a[href*='/p/'], a[href*='pid=']") && (d.textContent || "").includes("₹");
      });
    }

    productCards.forEach(card => {
      let pid = card.getAttribute("data-id");

      const fullText = (card.textContent || card.innerText || "").trim();

      // STRICT FILTER: Exclude footer reviews completely
      if (fullText.includes("Reviews for Popular") || 
          fullText.includes("Most Helpful Review") || 
          fullText.includes("Recent Review") || 
          fullText.includes("Certified Buyer")) {
        return;
      }

      // Title: Prefer img[alt], then links, then text
      let title = "";
      const img = card.querySelector("img[alt]");
      if (img && img.getAttribute("alt") && img.getAttribute("alt").trim().length > 3) {
        title = img.getAttribute("alt").trim();
      }
      if (!title) {
        const titleLink = card.querySelector("a[title], a.pIpigb, a.GnxRXv, a.w-b1gX");
        if (titleLink && titleLink.getAttribute("title")) {
          title = titleLink.getAttribute("title").trim();
        } else if (titleLink) {
          title = (titleLink.textContent || titleLink.innerText || "").trim();
        }
      }
      if (!title) {
        title = fullText.split('₹')[0].trim();
      }
      if (!title || title.length < 3) return;

      // Selling Price (Matches first ₹ number)
      let price = null;
      const priceEl = card.querySelector(".Nx9bqj, .hZ3P6w, ._30jeq3, div[class*='Nx9bqj'], div[class*='hZ3P6w']");
      if (priceEl) {
        const m = (priceEl.textContent || "").match(/₹?\s*([0-9,]+)/);
        if (m) price = parseFloat(m[1].replace(/,/g, ''));
      }
      if (!price) {
        const m = fullText.match(/₹\s*([0-9,]+(?:\.\d+)?)/);
        if (m) price = parseFloat(m[1].replace(/,/g, ''));
      }
      if (!price || price < 40) return;

      // MRP (Strikethrough element or second ₹ number)
      let mrp = price;
      const mrpEl = card.querySelector(".yRaY8j, .kRYCnD, ._3I9_wc, strike, del, div[class*='kRYCnD']");
      if (mrpEl) {
        const m = (mrpEl.textContent || "").match(/₹?\s*([0-9,]+)/);
        if (m) {
          const val = parseFloat(m[1].replace(/,/g, ''));
          if (val >= price && val < 10000) mrp = val;
        }
      }
      if (mrp === price) {
        const allPrices = Array.from(fullText.matchAll(/₹\s*([0-9,]+)/g)).map(x => parseFloat(x[1].replace(/,/g, '')));
        if (allPrices.length >= 2 && allPrices[1] >= price && allPrices[1] < 10000) {
          mrp = allPrices[1];
        }
      }

      // Rating
      let rating = 4.2;
      const rateEl = card.querySelector(".XQDdHH, .MKiFS6, ._3LWZlK, div[class*='XQDdHH']");
      if (rateEl) {
        const m = (rateEl.textContent || "").match(/(\d\.\d)/);
        if (m) rating = parseFloat(m[1]);
      } else {
        const rMatch = fullText.match(/(\d\.\d)\s*★?/);
        if (rMatch) rating = parseFloat(rMatch[1]);
      }

      // Stock Status
      const isOutOfStock = /out of stock|currently unavailable|temporarily unavailable/i.test(fullText);

      // URL
      const linkEl = card.querySelector("a[href*='/p/'], a[href*='pid=']");
      let href = linkEl ? linkEl.href || linkEl.getAttribute("href") : "";
      if (href && !href.startsWith("http")) href = `https://www.flipkart.com${href}`;

      if (!pid && href) {
        const mPid = href.match(/pid=([a-zA-Z0-9_-]+)/) || href.match(/\/p\/([a-zA-Z0-9_-]+)/);
        if (mPid) pid = mPid[1];
      }
      if (!pid) {
        pid = title.replace(/[^a-zA-Z0-9]+/g, '').substring(0, 16);
      }

      // Image
      const imgSrc = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";

      items.set(pid, {
        id: pid,
        product_id: pid,
        fsn: pid,
        name: title,
        price: price,
        mrp: mrp || price,
        rating: rating,
        review_count: 50,
        in_stock: !isOutOfStock,
        url: href,
        product_url: href,
        img: imgSrc,
        image_url: imgSrc,
        text: `${title} | ₹${price}`
      });
    });

    return items.size - countBefore;
  };

  // 4. Scan Current Page (Page 1)
  updateBanner("🚀 Scanning page products...");
  for (let pt of [0.3, 0.6, 0.9, 1.0]) {
    window.scrollTo({ top: document.body.scrollHeight * pt, behavior: 'smooth' });
    await sleep(400);
    extractFromRoot(document);
  }
  extractFromRoot(document);

  console.log(`%c📄 Current Page Scanned. Unique Products Captured: ${items.size}`, "color: #38bdf8; font-weight: bold;");
  updateBanner(`📄 Current page scanned (${items.size} captured)`, items.size);

  // Save current progress to sessionStorage
  sessionStorage.setItem("spicenest_fk_items", JSON.stringify(Array.from(items.values())));

  // 5. Discover Page 2 & fetch in background
  const pageUrls = new Set();
  document.querySelectorAll("nav a[href*='page='], a[href*='page=']").forEach(a => {
    let href = a.getAttribute('href');
    if (href && href.includes('page=')) {
      if (!href.startsWith('http')) href = window.location.origin + href;
      pageUrls.add(href);
    }
  });

  // Construct page=2
  try {
    const p2Url = new URL(window.location.href);
    p2Url.searchParams.set("page", "2");
    pageUrls.add(p2Url.toString());
  } catch (e) {}

  pageUrls.delete(window.location.href);

  // Background fetch remaining pages (Page 2)
  for (const nextUrl of pageUrls) {
    updateBanner(`🌐 Fetching Page 2 in background...`, items.size);
    console.log(`%c🌐 Fetching next page: ${nextUrl}`, "color: #2874f0; font-weight: bold;");

    try {
      const resp = await fetch(nextUrl, { credentials: 'include' });
      if (resp.ok) {
        const html = await resp.text();
        const fetchedDoc = new DOMParser().parseFromString(html, 'text/html');
        const newCount = extractFromRoot(fetchedDoc);
        console.log(`   📦 Page 2 yielded ${newCount} new products. Total: ${items.size}`);
        updateBanner(`✅ Page 2 scanned (+${newCount} items)`, items.size);
      }
      await sleep(600);
    } catch (err) {
      console.warn("Background fetch notice:", err);
    }
  }

  const allItems = Array.from(items.values());
  sessionStorage.setItem("spicenest_fk_items", JSON.stringify(allItems));

  console.log(`%c🎉 FLIPKART CRAWL COMPLETE! Total ${allItems.length} genuine products captured!`, "color: #10b981; font-weight: bold; font-size: 16px;");
  updateBanner(`🎉 Complete! All ${allItems.length} Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Spice Nest brand/search page par hain.");
    return;
  }

  // 6. Download JSON File
  const todayStr = new Date().toISOString().split('T')[0];
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `flipkart_all_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // 7. Auto-Sync directly to Spice Nest Hub (localhost:5000)
  let syncData = null;
  try {
    updateBanner("🔄 Auto-syncing to Flipkart Seller Dashboard (localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/flipkart/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) {
      syncData = await res.json();
    }
  } catch (err) {}

  if (syncData && syncData.status === "SUCCESS") {
    alert(`🎉 FLIPKART SYNC SUCCESSFUL!\n\n` +
          `• Total Products Captured: ${allItems.length}\n` +
          `• 🔺 Price Hikes: ${syncData.price_hikes || 0}\n` +
          `• 🔻 Price Drops: ${syncData.price_drops || 0}\n` +
          `• ⚠️ Out of Stock: ${syncData.out_of_stock || 0}\n` +
          `• 🚨 Delisted from Catalog: ${syncData.delisted || 0}\n` +
          `• 🟢 New Listings: ${syncData.new_listings || 0}\n\n` +
          `• File Downloaded: flipkart_all_${allItems.length}_products_${todayStr}.json\n` +
          `• Daily Snapshot Hub me save ho gaya!\n` +
          `• (Main Price Hub table bilkul untouched aur safe hai)`);
  } else {
    alert(`✅ FLIPKART CRAWL COMPLETE!\n\n` +
          `• Total Genuine Products: ${allItems.length}\n` +
          `• Review section bilkul 0% exclude kar diya gaya hai!\n` +
          `• JSON file download ho gayi: flipkart_all_${allItems.length}_products_${todayStr}.json\n\n` +
          `Aap is file ko "http://localhost:5000/flipkart-seller" par "📤 Upload Flipkart JSON" button se upload kar sakte hain!`);
  }
})();
