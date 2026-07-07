let ordersData = [];

async function loadOrdersPage() {
    try {
        const depositResult = await getWallet();

        ordersData = [];

        if (depositResult) {
            ordersData.push({
                title: "Hamyon",
                status: "Tayyor"
            });
        }

        renderOrders();
    } catch (error) {
        console.error(error);
        tg.showAlert("Buyurtmalarni yuklashda xatolik.");
    }
}

function renderOrders() {
    tg.showAlert(
        `📜 Buyurtmalar\n\nJami: ${ordersData.length}`
    );
}

async function refreshOrders() {
    await loadOrdersPage();
}

async function openDepositOrders() {
    tg.showAlert("Deposit tarixi keyingi bosqichda ochiladi.");
}

async function openWithdrawOrders() {
    tg.showAlert("Withdraw tarixi keyingi bosqichda ochiladi.");
}

async function openCoinOrders() {
    tg.showAlert("Coin buyurtmalari keyingi bosqichda ochiladi.");
}

async function openWheelOrders() {
    tg.showAlert("Wheel buyurtmalari keyingi bosqichda ochiladi.");
}

async function openP2POrdersHistory() {
    tg.showAlert("P2P tarixi keyingi bosqichda ochiladi.");
}
