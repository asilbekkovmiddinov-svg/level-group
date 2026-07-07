let profileData = null;

async function loadProfilePage() {
    try {
        profileData = {
            telegram_id: TELEGRAM_ID,
            first_name: FIRST_NAME || "User",
            username: USERNAME || "",
        };

        renderProfile();
    } catch (error) {
        console.error(error);
        tg.showAlert("Profilni yuklashda xatolik.");
    }
}

function renderProfile() {
    if (!profileData) {
        return;
    }

    const usernameText = profileData.username
        ? `@${profileData.username}`
        : "Username yo'q";

    tg.showAlert(
        "👤 Profil\n\n" +
        `Ism: ${profileData.first_name}\n` +
        `Username: ${usernameText}\n` +
        `Telegram ID: ${profileData.telegram_id}`
    );
}

async function refreshProfile() {
    await loadProfilePage();
}
