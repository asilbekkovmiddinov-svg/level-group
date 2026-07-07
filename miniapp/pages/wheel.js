let wheelData = null;

async function loadWheelPage() {
    try {
        const result = await getWheelStatus();

        if (!result || result.success === false) {
            tg.showAlert("Baraban ma'lumotlarini yuklab bo'lmadi.");
            return;
        }

        wheelData = result.data || result;

        renderWheel();
    } catch (error) {
        console.error(error);
        tg.showAlert("Barabanni yuklashda xatolik.");
    }
}

function renderWheel() {
    if (!wheelData) {
        return;
    }

    const freeSpins = wheelData.free_spins ?? 0;
    const adSpins = wheelData.ad_spins ?? 0;

    tg.showAlert(
        "🎰 Baraban\n\n" +
        `🎁 Bepul aylantirish: ${freeSpins}\n` +
        `📺 Reklama aylantirish: ${adSpins}`
    );
}

async function spinFreeWheel() {
    tg.showAlert("Bepul aylantirish keyingi bosqichda ochiladi.");
}

async function spinAdWheel() {
    tg.showAlert("Reklama orqali aylantirish keyingi bosqichda ochiladi.");
}

async function refreshWheel() {
    await loadWheelPage();
}
