// ==============================================================================
// 🌶️ SPICE NEST - FLIPKART MULTI-PAGE CRAWLER (NO REVIEWS / 100% CLEAN PRODUCTS)
// ==============================================================================
// KAISE CHALAYEIN:
// 1. Flipkart par apni Brand/Search page kholein:
//    👉 https://www.flipkart.com/search?q=Spice+Nest
// 2. F12 dabayein (Console tab kholein)
// 3. Neeche diya gaya poora code paste karke ENTER dabayein.
//
// YEH SCRIPT:
// - Page 1, Page 2, Page 3... sabhi pages ke SARE products capture karega.
// - "Reviews for Popular Spice Nest Products" wale section ko 100% IGNORE karega.
// - Sirf genuine catalog products (data-id) aur unke exact selling prices lega.
// - Cart ya header button ko touch nahi karega.
// - `flipkart_all_products_YYYY-MM-DD.json` automatically download karega!
// - Spice Nest Hub (localhost:5000) me direct sync karega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🌶️ SPICE NEST FLIPKART CLEAN MULTI-PAGE CRAWLER (v3.0)", "color: #2874f0; font-weight: bold; font-size: 16px;");

  const STORE_URL = "https://www.flipkart.com/search?q=Spice+Nest";

  // 1. Safety Check: If on Cart or Checkout, prompt redirect
  const currentUrl = window.location.href.toLowerCase();
  if (currentUrl.includes("/cart") || currentUrl.includes("/mcheckout")) {
    const go = confirm("⚠️ DHYAN DEIN!\n\nAap abhi Flipkart Cart page par hain.\n\nKya aap Spice Nest Search page par jana chahte hain?");
    if (go) window.location.href = STORE_URL;
    return;
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const items = new Map();

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
        <span style="color: #2874f0; font-size: 14px; font-weight:700;">⚡ Flipkart Sync (Clean)</span>
        <span style="background: #2874f0; color:#fff; padding: 2px 8px; border-radius: 9999px; font-size: 11px;">Active</span>
      </div>
      <div style="color: #38bdf8; font-size: 13px; margin: 4px 0;">${msg}</div>
      <div style="color: #94a3b8; font-size: 11px; margin-top: 4px;">📦 Total Captured: <b style="color: #10b981; font-size: 15px;">${count}</b> Products</div>
    `;
  };

  // 3. Strict Product Extractor (Strictly excludes review widgets)
  const extractFromRoot = (rootDoc) => {
    let countBefore = items.size;

    // A. Genuine search product cards have data-id (Review section does NOT have data-id)
    const productCards = Array.from(rootDoc.querySelectorAll("div[data-id]"));

    productCards.forEach(card => {
      // STRICT FILTER: Exclude any review widgets, comments, or customer review blocks
      if (card.closest(".lvJbLV, [class*='review'], [class*='Review']")) return;

      const fullText = (card.innerText || card.textContent || "").trim();
      if (fullText.includes("Reviews for Popular") || 
          fullText.includes("Most Helpful Review") || 
          fullText.includes("Recent Review") || 
          fullText.includes("Certified Buyer")) {
        return; // Skip review section products completely!
      }

      const pid = card.getAttribute("data-id");
      if (!pid || items.has(pid)) return;

      // Extract Title
      let title = "";
      const titleLink = card.querySelector("a[title], a.pIpigb, a[class*='title'], a[class*='Title']");
      if (titleLink && titleLink.getAttribute("title")) {
        title = titleLink.getAttribute("title").trim();
      } else if (titleLink && titleLink.innerText) {
        title = titleLink.innerText.trim();
      }
      if (!title) {
        const img = card.querySelector("img[alt]");
        if (img && img.alt && img.alt.length > 3) title = img.alt.trim();
      }
      if (!title) {
        title = fullText.split('₹')[0].trim();
      }
      if (!title || title.length < 3) return;

      // Selling Price (Must be >= ₹50)
      let price = null;
      const pMatch = fullText.match(/₹\s*([0-9,]+(?:\.\d+)?)/);
      if (pMatch) price = parseFloat(pMatch[1].replace(/,/g, ''));
      if (!price || price < 50) return;

      // MRP
      let mrp = price;
      const allPrices = Array.from(fullText.matchAll(/₹\s*([0-9,]+(?:\.\d+)?)/g));
      if (allPrices.length > 1) {
        mrp = parseFloat(allPrices[1][1].replace(/,/g, ''));
      }

      // Rating
      let rating = 4.2;
      const rMatch = fullText.match(/(\d\.\d)\s*★?/);
      if (rMatch) rating = parseFloat(rMatch[1]);

      // URL
      const linkEl = card.querySelector("a[href*='/p/'], a[href*='pid=']");
      let href = linkEl ? linkEl.href : "";
      if (!href && linkEl) href = linkEl.getAttribute("href");
      if (href && !href.startsWith("http")) href = `https://www.flipkart.com${href}`;

      // Image
      const img = card.querySelector("img.UCc1lI, img");
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
        url: href,
        img: imgSrc,
        text: `${title} | ₹${price}`
      });
    });

    return items.size - countBefore;
  };

  // 4. Smooth scrolling for current page (Page 1)
  updateBanner("🚀 Scanning Page 1 products...");
  for (let pt of [0.4, 0.8, 1.0]) {
    window.scrollTo({ top: document.body.scrollHeight * pt, behavior: 'smooth' });
    await sleep(600);
    extractFromRoot(document);
  }
  extractFromRoot(document);

  console.log(`%c📄 [Page 1] Captured ${items.size} genuine products (Review section excluded)`, "color: #38bdf8; font-weight: bold;");
  updateBanner(`📄 Page 1 done (${items.size} captured)`, items.size);

  // 5. Discover all subsequent pages (Page 2, 3, 4...)
  const pageUrls = new Set();

  // A. Discover from Flipkart's on-screen pagination bar (Image 2)
  document.querySelectorAll("nav a[href*='page='], a[href*='page='], a.i2eZXn").forEach(a => {
    let href = a.getAttribute('href');
    if (href && href.includes('page=')) {
      if (!href.startsWith('http')) href = window.location.origin + href;
      pageUrls.add(href);
    }
  });

  // B. Also construct URL search params for up to page 5
  try {
    const baseObj = new URL(window.location.href);
    for (let p = 2; p <= 5; p++) {
      baseObj.searchParams.set("page", p.toString());
      pageUrls.add(baseObj.toString());
    }
  } catch (e) {}

  // Remove current URL if in set
  pageUrls.delete(window.location.href);

  // Sort URLs by page number
  const urlsToFetch = Array.from(pageUrls).sort((a, b) => {
    const pA = parseInt((a.match(/page=(\d+)/) || [0, 1])[1]);
    const pB = parseInt((b.match(/page=(\d+)/) || [0, 1])[1]);
    return pA - pB;
  });

  console.log(`🌐 Found ${urlsToFetch.length} page URLs to scan.`);

  // 6. Multi-page background fetching (Page 2, 3, 4...)
  let pageIdx = 2;
  for (const nextUrl of urlsToFetch) {
    const pMatch = nextUrl.match(/page=(\d+)/);
    const pNum = pMatch ? pMatch[1] : pageIdx;

    updateBanner(`🌐 Scanning Flipkart Page ${pNum}...`, items.size);
    console.log(`%c🌐 Fetching Flipkart Page ${pNum}: ${nextUrl}`, "color: #2874f0; font-weight: bold;");

    try {
      const resp = await fetch(nextUrl, { credentials: 'include' });
      if (!resp.ok) {
        console.warn(`Page ${pNum} returned status ${resp.status}`);
        break;
      }

      const html = await resp.text();
      const fetchedDoc = new DOMParser().parseFromString(html, 'text/html');
      const newCount = extractFromRoot(fetchedDoc);

      console.log(`   📦 Page ${pNum} yielded ${newCount} new genuine products. (Total: ${items.size})`);
      updateBanner(`✅ Page ${pNum} done (+${newCount} items)`, items.size);

      if (newCount === 0) {
        console.log(`🏁 No more products found on Page ${pNum}. Completed!`);
        break;
      }

      await sleep(1000); // Polite 1s delay
    } catch (err) {
      console.warn(`Error on Page ${pNum}:`, err);
      break;
    }
    pageIdx++;
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 FLIPKART CRAWL COMPLETE! Total ${allItems.length} products captured!`, "color: #10b981; font-weight: bold; font-size: 16px;");
  updateBanner(`🎉 Complete! All ${allItems.length} Genuine Products Captured!`, allItems.length);

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Flipkart search page par hain:\nhttps://www.flipkart.com/search?q=Spice+Nest");
    return;
  }

  // 7. Automatic JSON File Download
  const todayStr = new Date().toISOString().split('T')[0];
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `flipkart_all_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  // 8. Auto-Sync directly to Spice Nest Hub (localhost:5000)
  let directSynced = false;
  try {
    updateBanner("🔄 Auto-syncing to Spice Nest Hub (localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/flipkart/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) directSynced = true;
  } catch (err) {}

  if (directSynced) {
    alert(`🎉 SUCCESS!\n\n• Flipkart se total ${allItems.length} genuine products capture ho gaye!\n• Review section bilkul exclude kar diya gaya hai!\n• JSON file download ho gayi: flipkart_all_${allItems.length}_products_${todayStr}.json\n• Spice Nest Hub (localhost:5000) me direct sync ho gaya hai!`);
  } else {
    alert(`✅ SUCCESS!\n\n• Flipkart se total ${allItems.length} genuine products capture ho gaye!\n• Review section bilkul exclude kar diya gaya hai!\n• JSON file download ho gayi: flipkart_all_${allItems.length}_products_${todayStr}.json\n\nAap is file ko Spice Nest Hub par "📤 Upload Flipkart JSON" button se upload kar sakte hain!`);
  }
})();
