let walletData = null;

async function loadWalletPage() {
    try {
        const result = await getWallet();

        if (!result || result.success === false) {
            Modal.error("Hamyonni yuklab bo‘lmadi.");
            return;
        }

        walletData = result.data || result;

        renderWalletPage();
    } catch (error) {
        console.error(error);
        Modal.error("Hamyonni yuklashda xatolik.");
    }
}

function renderWalletPage() {
    const page = document.getElementById("homePage");

    const efc = Number(walletData?.efc_balance || 0).toLocaleString("uz-UZ");
    const uzs = Number(walletData?.uzs_balance || 0).toLocaleString("uz-UZ");

    document.getElementById("efcBalance").textContent = efc;
    document.getElementById("uzsBalance").textContent = uzs;

    if (!page) return;
}

async function refreshWallet() {
    await loadWalletPage();
}

async function openDeposit() {
    tg.showPopup({
        title: "UZS to‘ldirish",
        message: "To‘ldirish summasini bot orqali yuboring. WebApp deposit formasi V1.1 da qo‘shiladi.",
        buttons: [
            { type: "ok", text: "Tushunarli" }
        ]
    });
}

async function openWithdraw() {
    tg.showPopup({
        title: "UZS yechish",
        message: "Yechish so‘rovini bot orqali yuboring. WebApp withdraw formasi V1.1 da qo‘shiladi.",
        buttons: [
            { type: "ok", text: "Tushunarli" }
        ]
    });
}
