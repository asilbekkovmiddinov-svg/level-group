let profileData = null;

async function loadProfilePage() {
    Navbar.setActive("profile");
    showPage("profilePage", "Profil");

    profileData = {
        telegram_id: TELEGRAM_ID,
        first_name: FIRST_NAME || "User",
        username: USERNAME || "",
    };

    renderProfile();
}

function renderProfile() {
    const page = document.getElementById("profilePage");

    const usernameText = profileData.username
        ? `@${profileData.username}`
        : "Username yo‘q";

    page.innerHTML = `
        <div class="profile-box">
            <div class="avatar">LG</div>

            <h2>${profileData.first_name}</h2>
            <p class="gray">${usernameText}</p>
            <p class="green">● Online</p>

            <div class="stat-grid">
                <div class="stat-box">
                    <small>Telegram ID</small>
                    <strong>${profileData.telegram_id}</strong>
                </div>

                <div class="stat-box">
                    <small>Til</small>
                    <strong>UZ</strong>
                </div>

                <div class="stat-box">
                    <small>P2P reyting</small>
                    <strong>V1.1</strong>
                </div>

                <div class="stat-box">
                    <small>Savdolar</small>
                    <strong>V1.1</strong>
                </div>
            </div>
        </div>
    `;
}

async function refreshProfile() {
    await loadProfilePage();
}
