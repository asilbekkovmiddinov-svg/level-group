let p2pOrders = [];
let currentP2PType = "SELL";

async function loadP2PPage() {
    Navbar.setActive("p2p");
    showPage("p2pPage", "P2P Market");

    await loadP2POrders("SELL");
}

async function loadP2POrders(type = "SELL") {
    currentP2PType = type;

    const page = document.getElementById("p2pPage");

    page.innerHTML = `
        <div class="tab-row">
            <button class="tab-btn ${type === "SELL" ? "active" : ""}" onclick="loadP2POrders('SELL')">
                Sotish
            </button>
            <button class="tab-btn ${type === "BUY" ? "active" : ""}" onclick="loadP2POrders('BUY')">
                Sotib olish
            </button>
        </div>

        <div id="p2pList" class="p2p-list">
            <div class="empty-state">Yuklanmoqda...</div>
        </div>
    `;

    try {
        const result = await getOpenP2POrders(type);

        if (!result || result.success === false) {
            document.getElementById("p2pList").innerHTML =
                `<div class="empty-state">E’lonlarni yuklab bo‘lmadi.</div>`;
            return;
        }

        p2pOrders = result.data || [];
        renderP2POrders();
    } catch (error) {
        console.error(error);
        document.getElementById("p2pList").innerHTML =
            `<div class="empty-state">Xatolik yuz berdi.</div>`;
    }
}

function renderP2POrders() {
    const list = document.getElementById("p2pList");

    if (!p2pOrders.length) {
        list.innerHTML = `<div class="empty-state">Hozircha e’lonlar yo‘q.</div>`;
        return;
    }

    list.innerHTML = p2pOrders.map((order) => {
        return `
            <div class="list-card">
                <div class="profile-hero" style="margin-bottom:12px;">
                    <div class="avatar">LG</div>
                    <div>
                        <h3>Order #${order.id}</h3>
                        <p class="${order.owner_is_online ? "green" : "gray"}">
                            ${order.owner_online_text || "⚪ Offline"}
                        </p>
                        <small class="gray">
                            ${order.owner_last_seen_text || "Noma’lum"}
                        </small>
                    </div>
                </div>

                <p>📌 Tur: <b>${order.order_type}</b></p>
                <p>🪙 Qolgan EFC: <b>${formatNumber(order.remaining_efc)}</b></p>
                <p>💵 1 EFC: <b>${formatNumber(order.price_uzs)} UZS</b></p>
                <p>🔻 Minimal savdo: <b>${formatNumber(order.min_trade_efc)} EFC</b></p>
                <p>⏱ Javob vaqti: <b>${order.response_minutes} daqiqa</b></p>

                <button class="red-btn" onclick="openP2PTrade(${order.id})">
                    🤝 Savdo qilish
                </button>
            </div>
        `;
    }).join("");
}

function openP2PTrade(orderId) {
    tg.showPopup({
        title: "P2P savdo",
        message: `Order #${orderId} bo‘yicha savdo bot orqali yakunlanadi. WebApp savdo formasi V1.1 da qo‘shiladi.`,
        buttons: [
            { type: "ok", text: "Tushunarli" }
        ]
    });
}

async function refreshP2P() {
    await loadP2POrders(currentP2PType);
}

function formatNumber(value) {
    return Number(value || 0).toLocaleString("uz-UZ", {
        maximumFractionDigits: 4,
    });
}
