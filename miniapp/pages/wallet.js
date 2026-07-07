let walletData = null;

async function loadWalletPage() {
    try {
        const result = await getWallet();

        if (!result || result.success === false) {
            tg.showAlert("Hamyonni yuklab bo'lmadi.");
            return;
        }

        walletData = result.data || result;

        renderWallet();
    } catch (error) {
        console.error(error);
        tg.showAlert("Hamyonni yuklashda xatolik.");
    }
}

function renderWallet() {
    if (!walletData) {
        return;
    }

    const efc = Number(walletData.efc_balance || 0).toLocaleString("uz-UZ");
    const uzs = Number(walletData.uzs_balance || 0).toLocaleString("uz-UZ");

    document.getElementById("efcBalance").textContent = efc;
    document.getElementById("uzsBalance").textContent = uzs;
}

async function refreshWallet() {
    await loadWalletPage();
}

async function openDeposit() {
    tg.showAlert("Deposit bo'limi keyingi bosqichda ochiladi.");
}

async function openWithdraw() {
    tg.showAlert("Withdraw bo'limi keyingi bosqichda ochiladi.");
}
