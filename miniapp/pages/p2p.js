let p2pOrders = [];
let myP2POrders = [];
let myP2PTrades = [];

async function loadP2PPage() {
    try {
        const result = await getOpenP2POrders();

        if (!result || result.success === false) {
            tg.showAlert("P2P e'lonlarini yuklab bo'lmadi.");
            return;
        }

        p2pOrders = result.data || [];

        renderP2P();
    } catch (error) {
        console.error(error);
        tg.showAlert("P2P yuklashda xatolik.");
    }
}

async function loadMyP2P() {
    try {
        const orders = await getMyP2POrders();
        const trades = await getMyP2PTrades();

        myP2POrders = orders.data || [];
        myP2PTrades = trades.data || [];
    } catch (error) {
        console.error(error);
    }
}

function renderP2P() {
    tg.showAlert(
        `P2P Market\n\nFaol e'lonlar: ${p2pOrders.length}`
    );
}

async function refreshP2P() {
    await loadP2PPage();
}

async function openBuyOrders() {
    tg.showAlert("Sotib olish sahifasi keyingi bosqichda ochiladi.");
}

async function openSellOrders() {
    tg.showAlert("Sotish sahifasi keyingi bosqichda ochiladi.");
}

async function openMyOrders() {
    await loadMyP2P();

    tg.showAlert(
        `Mening e'lonlarim: ${myP2POrders.length}\n` +
        `Mening savdolarim: ${myP2PTrades.length}`
    );
}

async function openP2PHistory() {
    const result = await getP2PHistory();

    if (!result || result.success === false) {
        tg.showAlert("Tarix yuklanmadi.");
        return;
    }

    tg.showAlert(
        `Yakunlangan savdolar: ${(result.data || []).length}`
    );
}
