let wheelData = null;

async function loadWheelPage() {
    Navbar.setActive("wheel");
    showPage("wheelPage", "Wheel");

    const page = document.getElementById("wheelPage");

    page.innerHTML = `
        <div class="wheel-circle">
            <button class="spin-btn" onclick="spinFreeWheel()">SPIN</button>
        </div>

        <div id="wheelInfo" class="list-card">
            Yuklanmoqda...
        </div>

        <button class="red-btn" onclick="spinFreeWheel()">
            🎁 Bepul aylantirish
        </button>

        <button class="red-btn" onclick="spinAdWheel()">
            ▶️ Reklama orqali aylantirish
        </button>
    `;

    await loadWheelStatus();
}


async function loadWheelStatus() {
    try {
        const result = await getWheelStatus();

        if (!result || result.success === false) {
            document.getElementById("wheelInfo").innerHTML =
                "Baraban ma’lumotlari yuklanmadi.";
            return;
        }

        wheelData = result.data || result;

        renderWheelInfo();
    } catch (error) {
        console.error(error);

        document.getElementById("wheelInfo").innerHTML =
            "Barabanni yuklashda xatolik.";
    }
}


function renderWheelInfo() {
    const freeSpins = wheelData?.free_spins ?? 0;
    const adSpins = wheelData?.ad_spins ?? 0;

    document.getElementById("wheelInfo").innerHTML = `
        <p>🎁 Bepul aylantirish: <b>${freeSpins}</b></p>
        <p>▶️ Reklama aylantirish: <b>${adSpins}</b></p>
    `;
}


async function spinFreeWheel() {
    tg.showPopup({
        title: "Wheel",
        message: "WebApp spin animatsiyasi V1.1 da qo‘shiladi. Hozircha baraban bot orqali ishlaydi.",
        buttons: [
            { type: "ok", text: "Tushunarli" }
        ]
    });
}


async function spinAdWheel() {
    tg.showPopup({
        title: "Reklama spin",
        message: "Reklama orqali aylantirish WebApp V1.1 da qo‘shiladi.",
        buttons: [
            { type: "ok", text: "Tushunarli" }
        ]
    });
}


async function refreshWheel() {
    await loadWheelStatus();
}
