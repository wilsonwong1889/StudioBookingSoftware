import { api } from "../api.js?v=20260401r";
import { API_BASE_URL, getSearchParam } from "../config.js?v=20260401r";
import { elements, toggleHidden } from "../dom.js?v=20260401r";
import { persistToken, setState } from "../state.js?v=20260401r";

let pendingTwoFactorToken = null;
let pendingTwoFactorMethod = "email";

function getLoginTwoFactorForm() {
  return document.getElementById("login-2fa-form");
}

function getLoginTwoFactorCopy() {
  return document.getElementById("login-2fa-copy");
}

function getLoginTwoFactorResendButton() {
  return document.getElementById("login-2fa-resend-button");
}

function getLoginTwoFactorCancelButton() {
  return document.getElementById("login-2fa-cancel-button");
}

function activateTab(tab) {
  if (!elements.loginForm || !elements.signupForm) {
    return;
  }
  elements.authTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === tab);
  });
  elements.loginForm.classList.toggle("hidden", tab !== "login");
  elements.signupForm.classList.toggle("hidden", tab !== "signup");
  getLoginTwoFactorForm()?.classList.add("hidden");
}

function setTwoFactorStep(method) {
  pendingTwoFactorMethod = method || "email";
  if (elements.loginForm) {
    elements.loginForm.classList.add("hidden");
  }
  if (elements.signupForm) {
    elements.signupForm.classList.add("hidden");
  }
  const twoFactorForm = getLoginTwoFactorForm();
  if (twoFactorForm) {
    twoFactorForm.reset();
    twoFactorForm.classList.remove("hidden");
  }
  const copy = getLoginTwoFactorCopy();
  if (copy) {
    copy.textContent = `Enter the 6-digit verification code sent by ${pendingTwoFactorMethod === "sms" ? "SMS" : "email"}.`;
  }
}

function clearTwoFactorStep() {
  pendingTwoFactorToken = null;
  pendingTwoFactorMethod = "email";
  getLoginTwoFactorForm()?.classList.add("hidden");
}

async function requestJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.detail || "Request failed");
  }
  return data;
}

export function initAuthView(actions) {
  elements.authTabs.forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.authTab));
  });

  if (getSearchParam("mode") === "signup") {
    activateTab("signup");
  }

  if (elements.loginForm && elements.signupForm) {
    elements.loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.loginForm);
      try {
        setState({ message: "Logging in..." });
        const session = await api.login(form.get("email"), form.get("password"));
        if (session.two_factor_required) {
          pendingTwoFactorToken = session.two_factor_token;
          setTwoFactorStep(session.two_factor_method);
          setState({ message: `Verification code sent by ${session.two_factor_method === "sms" ? "SMS" : "email"}.` });
          return;
        }
        persistToken(session.access_token);
        clearTwoFactorStep();
        elements.loginForm.reset();
        await actions.refreshSession("Logged in successfully.");
      } catch (error) {
        setState({ message: error.message });
      }
    });

    elements.signupForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.signupForm);
      const payload = {
        email: form.get("email"),
        password: form.get("password"),
        full_name: form.get("full_name"),
        phone: form.get("phone") || null,
      };

      try {
        setState({ message: "Creating account..." });
        await api.signup(payload);
        const session = await api.login(payload.email, payload.password);
        if (session.two_factor_required) {
          pendingTwoFactorToken = session.two_factor_token;
          setTwoFactorStep(session.two_factor_method);
          setState({ message: `Account created. Verification code sent by ${session.two_factor_method === "sms" ? "SMS" : "email"}.` });
          return;
        }
        persistToken(session.access_token);
        clearTwoFactorStep();
        elements.signupForm.reset();
        await actions.refreshSession("Account created.");
        activateTab("login");
      } catch (error) {
        setState({ message: error.message });
      }
    });
  }

  getLoginTwoFactorForm()?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(getLoginTwoFactorForm());

    if (!pendingTwoFactorToken) {
      setState({ message: "Start login again to request a new verification code." });
      activateTab("login");
      return;
    }

    try {
      setState({ message: "Verifying code..." });
      const session = await requestJson("/api/auth/verify-2fa", {
        two_factor_token: pendingTwoFactorToken,
        code: String(form.get("code") || "").trim(),
      });
      persistToken(session.access_token);
      clearTwoFactorStep();
      elements.loginForm?.reset();
      await actions.refreshSession("Two-factor verification complete.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  getLoginTwoFactorResendButton()?.addEventListener("click", async () => {
    if (!pendingTwoFactorToken) {
      setState({ message: "Start login again to request a new verification code." });
      activateTab("login");
      return;
    }

    try {
      setState({ message: "Sending a new verification code..." });
      const session = await requestJson("/api/auth/resend-2fa", {
        two_factor_token: pendingTwoFactorToken,
      });
      pendingTwoFactorToken = session.two_factor_token;
      setTwoFactorStep(session.two_factor_method);
      setState({ message: `New verification code sent by ${session.two_factor_method === "sms" ? "SMS" : "email"}.` });
    } catch (error) {
      setState({ message: error.message });
    }
  });

  getLoginTwoFactorCancelButton()?.addEventListener("click", () => {
    clearTwoFactorStep();
    activateTab("login");
    setState({ message: "Two-factor sign-in cancelled." });
  });

  const handleLogout = async () => {
    clearTwoFactorStep();
    persistToken(null);
    await actions.clearSession();
  };

  if (elements.logoutButton) {
    elements.logoutButton.addEventListener("click", handleLogout);
  }
  if (elements.headerLogoutButton) {
    elements.headerLogoutButton.addEventListener("click", handleLogout);
  }
}

export function renderAuthView(state) {
  const isSessionRestoring = Boolean(state.token && !state.currentUser);
  if (state.currentUser) {
    clearTwoFactorStep();
  }

  if (elements.logoutButton) {
    elements.logoutButton.classList.toggle("hidden", !state.currentUser);
  }

  if (elements.accountAuthPanel) {
    toggleHidden(elements.accountAuthPanel, Boolean(state.currentUser || isSessionRestoring));
  }

  if (elements.accountHeroTitle) {
    elements.accountHeroTitle.textContent = state.currentUser
      ? "Your account is ready."
      : "Access and profile live in one clean place.";
  }

  if (elements.accountHeroCopy) {
    elements.accountHeroCopy.textContent = state.currentUser
      ? "Update your personal details, password, and reminder preferences here."
      : "Use this page for account entry, profile updates, password changes, and reminder preferences.";
  }

  if (elements.accountSummaryCard && elements.accountSummaryName && elements.accountSummaryEmail) {
    toggleHidden(elements.accountSummaryCard, !state.currentUser);
    if (state.currentUser) {
      elements.accountSummaryName.textContent = `Welcome, ${
        state.currentUser.full_name || state.currentUser.email
      }.`;
      elements.accountSummaryEmail.textContent = state.currentUser.email;
    }
  }

  if (elements.headerAccountLink) {
    elements.headerAccountLink.href = "/account";
    elements.headerAccountLink.textContent = state.currentUser ? "My account" : "Log in";
  }

  if (elements.headerSecondaryLink) {
    if (state.currentUser?.is_admin) {
      elements.headerSecondaryLink.href = "/admin";
      elements.headerSecondaryLink.textContent = "Admin";
      elements.headerSecondaryLink.classList.remove("hidden");
    } else if (state.currentUser) {
      elements.headerSecondaryLink.href = "/bookings";
      elements.headerSecondaryLink.textContent = "My bookings";
      elements.headerSecondaryLink.classList.remove("hidden");
    } else {
      elements.headerSecondaryLink.href = "/account?mode=signup";
      elements.headerSecondaryLink.textContent = "Create account";
      elements.headerSecondaryLink.classList.remove("hidden");
    }
  }

  if (elements.headerLogoutButton) {
    elements.headerLogoutButton.classList.toggle("hidden", !state.currentUser);
  }
}
