let orderHistory = [];

async function loadOrdersPage() {

    Navbar.setActive("orders");
    showPage("ordersPage", "Buyurtmalar");

    const page = document.getElementById("ordersPage");

    page.innerHTML = `
        <div class="list-card">
            <h3>📜 Buyurtmalar</h3>

            <p class="gray">
                Bu yerda Coin, Deposit, Withdraw, P2P va Wheel buyurtmalari ko'rinadi.
            </p>
        </div>

        <div id="ordersList">
            <div class="empty-state">
                Buyurtmalar yuklanmoqda...
            </div>
        </div>
    `;

    await loadOrders();
}

async function loadOrders() {

    orderHistory = [];

    const wallet = await getWallet();

    if (wallet) {

        orderHistory.push({
            title: "Wallet",
            status: "ACTIVE"
        });

    }

    renderOrders();
}

function renderOrders() {

    const container = document.getElementById("ordersList");

    if (!orderHistory.length) {

        container.innerHTML = `
            <div class="empty-state">
                Buyurtmalar topilmadi.
            </div>
        `;

        return;

    }

    container.innerHTML = orderHistory.map(order => `

        <div class="list-card">

            <h3>${order.title}</h3>

            <p class="green">
                ${order.status}
            </p>

        </div>

    `).join("");

}

async function refreshOrders() {

    await loadOrders();

}
