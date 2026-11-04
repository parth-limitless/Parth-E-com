// ==============================================================================
// 🌶️ SPICE NEST - MEESHO ALL-PAGES 1-CLICK SCRAPER & DIRECT HUB AUTO-SYNC
// ==============================================================================
// Kaise chalayein:
// 1. Meesho par apni store / catalog page kholein (e.g. https://www.meesho.com/SpiceNestImpexPrivatelimited?ms=2)
// 2. F12 (Inspect -> Console) dabayein
// 3. Poora code paste karke ENTER dabayein
//
// Yeh script Page 1 se lekar Page 5 (ya aage ke sabhi pages) par khud jaakar
// sabhi products extract karega aur direct Spice Nest Hub me sync kar dega!
// ==============================================================================

(async () => {
  console.clear();
  console.log("%c🚀 Starting Spice Nest Meesho Complete Store Catalog Crawler...", "color: #10b981; font-weight: bold; font-size: 14px;");
  
  const items = new Map();
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  // 1. Current DOM se products collect karne ka function
  const collectCurrentPage = () => {
    let beforeCount = items.size;
    document.querySelectorAll("a[href*='/p/']").forEach(a => {
      let m = a.href.match(/\/p\/([a-zA-Z0-9_-]+)/);
      if (m && !items.has(m[1])) {
        let cardText = a.innerText.trim().replace(/\n+/g, ' | ');
        let img = a.querySelector("img");
        let imgSrc = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";
        items.set(m[1], {
          id: m[1],
          url: a.href,
          text: cardText,
          img: imgSrc
        });
      }
    });
    return items.size - beforeCount;
  };

  // 2. Smooth scrolling taaki images aur dynamic products lazy-load ho sakein
  const smoothScrollToBottom = async () => {
    window.scrollTo({ top: document.body.scrollHeight * 0.35, behavior: 'smooth' });
    await sleep(600);
    window.scrollTo({ top: document.body.scrollHeight * 0.7, behavior: 'smooth' });
    await sleep(600);
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    await sleep(1000);
  };

  // 3. Specific page number ka leaf element live DOM se dhoondhna
  const findPageElement = (numStr) => {
    const candidates = Array.from(document.querySelectorAll('button, a, span, div, p'));
    return candidates.find(el => {
      if (el.children.length > 0) return false; // Sirf leaf element chahiye (no parent wrapper)
      if (el.textContent.trim() !== numStr) return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0; // Screen par visible hona chahiye
    });
  };

  // 4. "NEXT" button ka live element dhoondhna
  const findNextButton = () => {
    const candidates = Array.from(document.querySelectorAll('button, a, span, div, p'));
    return candidates.find(el => {
      const txt = el.textContent.trim().toUpperCase();
      if (['NEXT', '>', '»', 'AGLA', 'NEXT PAGE'].includes(txt)) {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }
      return false;
    });
  };

  let currentPage = 1;
  const maxPages = 25; // Safety limit

  while (currentPage <= maxPages) {
    console.log(`%c📄 [Page ${currentPage}] Scanning products...`, "color: #38bdf8; font-weight: bold;");

    // Bottom tak scroll karein
    await smoothScrollToBottom();
    const newlyAdded = collectCurrentPage();
    console.log(`   📦 Found ${newlyAdded} new products on Page ${currentPage} (Total captured: ${items.size})`);

    const nextPageNum = currentPage + 1;

    // Next page button dhoondein (Pehele specific number, fir Next text)
    let nextBtn = findPageElement(String(nextPageNum));
    let usedNextText = false;

    if (!nextBtn) {
      nextBtn = findNextButton();
      usedNextText = true;
    }

    // Agar koi next button nahi mila, iska matlab last page par pahunch gaye!
    if (!nextBtn) {
      console.log(`%c🏁 Last Page (${currentPage}) reached! Koi aage ka page nahi mila. Completed!`, "color: #f59e0b; font-weight: bold;");
      break;
    }

    console.log(`   👉 Clicking Page ${nextPageNum}${usedNextText ? ' (via Next button)' : ''}...`);

    // Button ko center me scroll karein aur click trigger karein
    nextBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(400);

    // Native click + React Synthetic Event dispatch (for maximum compatibility)
    nextBtn.click();
    nextBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));

    // Wait 2 seconds for Meesho to load next page products
    await sleep(2200);

    // Naye page ko bhi scroll karke collect karein
    await smoothScrollToBottom();
    collectCurrentPage();

    currentPage++;
  }

  const allItems = Array.from(items.values());
  console.log(`%c🎉 SCRAPING COMPLETE! Total ${allItems.length} products captured across ${currentPage} pages.`, "color: #10b981; font-weight: bold; font-size: 15px;");

  if (allItems.length === 0) {
    alert("⚠️ Koi products capture nahi hue! Kripya check karein ki aap Meesho Storefront page par hain.");
    return;
  }

  // 1. Direct Local Hub Sync (Bina download/upload kiye auto-post)
  let synced = false;
  try {
    console.log("🔄 Syncing directly to Spice Nest Hub (http://localhost:5000)...");
    const res = await fetch("http://localhost:5000/api/meesho/upload-json", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(allItems)
    });
    if (res.ok) {
      const data = await res.json();
      console.log("✅ Sync Response:", data);
      alert(`🎉 SUCCESS!\n\nSabhi ${allItems.length} products sabhi pages se nikaal kar Spice Nest Hub me DIRECT SYNC ho gaye hain!\n\n• Total Items: ${allItems.length}\n• Exact Selling Prices: Updated\n• Rating & Sentiment Matrix: Updated`);
      synced = true;
    }
  } catch (err) {
    console.warn("⚠️ Direct Hub sync not reachable (server offline or CORS). Downloading JSON backup...", err);
  }

  // 2. Download JSON Backup File
  const blob = new Blob([JSON.stringify(allItems, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const todayStr = new Date().toISOString().split('T')[0];
  a.download = `meesho_all_${allItems.length}_products_${todayStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  if (!synced) {
    alert(`✅ Done! Sabhi ${allItems.length} products ki JSON file download ho gayi hai.\n\nAap is file ko Spice Nest Hub par "📤 Upload Meesho JSON" button se upload kar sakte hain!`);
  }
})();

