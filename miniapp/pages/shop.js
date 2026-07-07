let shopProducts = [];

async function loadShopPage() {
    try {
        const result = await getProducts();

        if (!result || result.success === false) {
            tg.showAlert("Mahsulotlarni yuklab bo'lmadi.");
            return;
        }

        shopProducts = result.data || result || [];

        renderShop();
    } catch (error) {
        console.error(error);
        tg.showAlert("Shop yuklashda xatolik.");
    }
}

function renderShop() {
    tg.showAlert(
        "Coin sotib olish WebApp ichida keyingi bosqichda to'liq ochiladi."
    );
}

async function createShopOrder(productId) {
    try {
        const result = await createOrder(TELEGRAM_ID, productId);

        if (!result || result.success === false) {
            tg.showAlert(result?.message || "Buyurtma yaratilmadi.");
            return;
        }

        tg.showAlert("Buyurtma yaratildi.");
    } catch (error) {
        console.error(error);
        tg.showAlert("Buyurtma yaratishda xatolik.");
    }
}
