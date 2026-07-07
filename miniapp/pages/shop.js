let products = [];

async function loadShopPage() {
    Navbar.setActive("shop");
    showPage("shopPage", "Coin Shop");

    const page = document.getElementById("shopPage");

    page.innerHTML = `
        <div id="shopProducts">
            <div class="empty-state">
                Mahsulotlar yuklanmoqda...
            </div>
        </div>
    `;

    try {
        const result = await getProducts();

        if (!result || result.success === false) {
            document.getElementById("shopProducts").innerHTML = `
                <div class="empty-state">
                    Mahsulotlarni yuklab bo'lmadi.
                </div>
            `;
            return;
        }

        products = result.data || [];

        renderProducts();

    } catch (error) {

        console.error(error);

        document.getElementById("shopProducts").innerHTML = `
            <div class="empty-state">
                Xatolik yuz berdi.
            </div>
        `;

    }
}

function renderProducts() {

    const container = document.getElementById("shopProducts");

    if (!products.length) {

        container.innerHTML = `
            <div class="empty-state">
                Mahsulotlar topilmadi.
            </div>
        `;

        return;

    }

    container.innerHTML = products.map(product => `

        <div class="list-card">

            <h3>${product.name}</h3>

            <p>
                🪙 Coin:
                <b>${formatMoney(product.coin_amount)}</b>
            </p>

            <p>
                💵 Narx:
                <b>${formatMoney(product.price)} UZS</b>
            </p>

            <button
                class="red-btn"
                onclick="buyProduct(${product.id})"
            >
                🛒 Sotib olish
            </button>

        </div>

    `).join("");

}

async function buyProduct(productId) {

    const result = await createOrder(productId);

    if (!result || result.success === false) {

        Modal.error(
            result?.message || "Buyurtma yaratilmadi."
        );

        return;

    }

    Modal.success(
        "Buyurtma muvaffaqiyatli yaratildi."
    );

}

async function refreshShop() {

    await loadShopPage();

}

function formatMoney(value) {

    return Number(value || 0).toLocaleString("uz-UZ");

}
