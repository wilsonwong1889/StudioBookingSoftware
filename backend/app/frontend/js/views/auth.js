import { api } from "../api.js?v=20260401r";
import { API_BASE_URL, getSearchParam } from "../config.js?v=20260401r";
import { elements, toggleHidden } from "../dom.js?v=20260401ab";
import { persistToken, setState } from "../state.js?v=20260401r";

let pendingTwoFactorToken = null;
let pendingTwoFactorMethod = "email";

function currentResetToken() {
  return getSearchParam("reset_token");
}

function clearLoginFieldFeedback() {
  if (elements.loginEmailFeedback) {
    elements.loginEmailFeedback.textContent = "";
    elements.loginEmailFeedback.classList.add("hidden");
  }
  if (elements.loginPasswordFeedback) {
    elements.loginPasswordFeedback.textContent = "";
    elements.loginPasswordFeedback.classList.add("hidden");
  }
}

function setLoginFieldFeedback(field, message) {
  const target =
    field === "password" ? elements.loginPasswordFeedback : elements.loginEmailFeedback;
  if (!target) {
    return;
  }
  target.textContent = message;
  target.classList.remove("hidden");
}

function hideAuthFeedback() {
  if (!elements.authFeedback) {
    return;
  }
  elements.authFeedback.textContent = "";
  elements.authFeedback.classList.add("hidden");
  elements.authFeedback.classList.remove("is-error", "is-success");
}

function showAuthFeedback(message, tone = "neutral") {
  if (!elements.authFeedback) {
    return;
  }
  elements.authFeedback.textContent = message;
  elements.authFeedback.classList.remove("hidden", "is-error", "is-success");
  elements.authFeedback.classList.toggle("is-error", tone === "error");
  elements.authFeedback.classList.toggle("is-success", tone === "success");
}

function clearPasswordMatchFeedback(target) {
  if (!target) {
    return;
  }
  target.textContent = "";
  target.classList.add("hidden");
  target.classList.remove("is-match", "is-mismatch");
}

function updatePasswordMatchFeedback(target, passwordValue, confirmValue) {
  if (!target) {
    return true;
  }
  const password = String(passwordValue || "");
  const confirm = String(confirmValue || "");

  if (!password && !confirm) {
    clearPasswordMatchFeedback(target);
    return true;
  }

  target.classList.remove("hidden", "is-match", "is-mismatch");
  if (password && confirm && password === confirm) {
    target.textContent = "Passwords match.";
    target.classList.add("is-match");
    return true;
  }

  target.textContent = "Passwords do not match.";
  target.classList.add("is-mismatch");
  return false;
}

function setAuthMode(mode, { preserveFeedback = false } = {}) {
  if (!preserveFeedback) {
    hideAuthFeedback();
  }
  clearLoginFieldFeedback();
  clearPasswordMatchFeedback(elements.signupPasswordMatchFeedback);
  clearPasswordMatchFeedback(elements.resetPasswordMatchFeedback);

  const loginFamilyModes = new Set([
    "login",
    "two-factor",
    "forgot-password",
    "reset-password",
  ]);
  const activeTab = loginFamilyModes.has(mode) ? "login" : "signup";

  elements.authTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === activeTab);
  });

  toggleHidden(elements.loginForm, mode !== "login");
  toggleHidden(elements.login2faForm, mode !== "two-factor");
  toggleHidden(elements.forgotPasswordForm, mode !== "forgot-password");
  toggleHidden(elements.resetPasswordForm, mode !== "reset-password");
  toggleHidden(elements.signupForm, mode !== "signup");
}

function activateTab(tab) {
  pendingTwoFactorToken = null;
  pendingTwoFactorMethod = "email";
  setAuthMode(tab === "signup" ? "signup" : "login");
}

function setTwoFactorStep(method) {
  pendingTwoFactorMethod = method || "email";
  setAuthMode("two-factor");
  if (elements.login2faForm) {
    elements.login2faForm.reset();
  }
  if (elements.login2faCopy) {
    elements.login2faCopy.textContent = `Enter the 6-digit verification code sent by ${
      pendingTwoFactorMethod === "sms" ? "SMS" : "email"
    }.`;
  }
}

function clearTwoFactorStep() {
  pendingTwoFactorToken = null;
  pendingTwoFactorMethod = "email";
}

async function requestJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? data.detail
        : "Request failed";
    throw new Error(detail);
  }
  return data;
}

function applyLoginError(message) {
  clearLoginFieldFeedback();
  const normalizedMessage = String(message || "Log in failed.");
  const lowered = normalizedMessage.toLowerCase();

  if (lowered.includes("valid email")) {
    setLoginFieldFeedback("email", "Enter a real email address to continue.");
  } else if (lowered.includes("couldn't find an account")) {
    setLoginFieldFeedback("email", "We could not find an account with that email.");
  } else if (lowered.includes("wrong password")) {
    setLoginFieldFeedback("password", "That password did not match the account.");
  }

  showAuthFeedback(normalizedMessage, "error");
}

export function initAuthView(actions) {
  elements.authTabs.forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.authTab));
  });

  const initialResetToken = currentResetToken();
  if (initialResetToken) {
    setAuthMode("reset-password");
    showAuthFeedback("Choose a new password for your account.", "neutral");
  } else if (getSearchParam("mode") === "signup") {
    setAuthMode("signup");
  } else {
    setAuthMode("login");
  }

  if (elements.loginForm && elements.signupForm) {
    const updateSignupPasswordMatch = () =>
      updatePasswordMatchFeedback(
        elements.signupPasswordMatchFeedback,
        elements.signupForm?.elements.password?.value,
        elements.signupForm?.elements.confirm_password?.value,
      );
    elements.signupForm.elements.password?.addEventListener("input", updateSignupPasswordMatch);
    elements.signupForm.elements.confirm_password?.addEventListener("input", updateSignupPasswordMatch);

    elements.loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.loginForm);
      clearLoginFieldFeedback();
      hideAuthFeedback();

      try {
        setState({ message: "Logging in..." });
        const session = await api.login(form.get("email"), form.get("password"));
        if (session.two_factor_required) {
          pendingTwoFactorToken = session.two_factor_token;
          setTwoFactorStep(session.two_factor_method);
          showAuthFeedback(
            `Verification code sent by ${
              session.two_factor_method === "sms" ? "SMS" : "email"
            }.`,
            "success",
          );
          setState({
            message: `Verification code sent by ${
              session.two_factor_method === "sms" ? "SMS" : "email"
            }.`,
          });
          return;
        }
        persistToken(session.access_token);
        clearTwoFactorStep();
        hideAuthFeedback();
        elements.loginForm.reset();
        await actions.refreshSession("Logged in successfully.");
      } catch (error) {
        applyLoginError(error.message);
        setState({ message: error.message });
      }
    });

    elements.signupForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.signupForm);
      const password = String(form.get("password") || "");
      const confirmPassword = String(form.get("confirm_password") || "");

      if (!updateSignupPasswordMatch()) {
        const message = "Passwords do not match yet.";
        showAuthFeedback(message, "error");
        setState({ message });
        return;
      }

      const payload = {
        email: form.get("email"),
        password,
        full_name: form.get("full_name"),
        phone: form.get("phone") || null,
      };

      hideAuthFeedback();

      try {
        setState({ message: "Creating account..." });
        await api.signup(payload);
        const session = await api.login(payload.email, payload.password);
        if (session.two_factor_required) {
          pendingTwoFactorToken = session.two_factor_token;
          setTwoFactorStep(session.two_factor_method);
          showAuthFeedback(
            `Account created. Verification code sent by ${
              session.two_factor_method === "sms" ? "SMS" : "email"
            }.`,
            "success",
          );
          setState({
            message: `Account created. Verification code sent by ${
              session.two_factor_method === "sms" ? "SMS" : "email"
            }.`,
          });
          return;
        }
        persistToken(session.access_token);
        clearTwoFactorStep();
        hideAuthFeedback();
        elements.signupForm.reset();
        clearPasswordMatchFeedback(elements.signupPasswordMatchFeedback);
        await actions.refreshSession("Account created.");
        activateTab("login");
      } catch (error) {
        showAuthFeedback(error.message, "error");
        setState({ message: error.message });
      }
    });
  }

  elements.forgotPasswordLink?.addEventListener("click", () => {
    clearTwoFactorStep();
    setAuthMode("forgot-password");
    showAuthFeedback("Enter your email and we will send a reset link.", "neutral");
  });

  elements.forgotPasswordBackButton?.addEventListener("click", () => {
    setAuthMode("login");
  });

  elements.resetPasswordBackButton?.addEventListener("click", () => {
    window.history.replaceState({}, "", "/account");
    setAuthMode("login");
  });

  elements.forgotPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.forgotPasswordForm);
    const email = String(form.get("email") || "").trim();

    try {
      setState({ message: "Sending password reset link..." });
      const response = await requestJson("/api/auth/forgot-password", { email });
      if (elements.loginForm?.email) {
        elements.loginForm.email.value = email;
      }
      elements.forgotPasswordForm.reset();
      setAuthMode("login", { preserveFeedback: true });
      showAuthFeedback(response.message, "success");
      setState({ message: response.message });
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  const updateResetPasswordMatch = () =>
    updatePasswordMatchFeedback(
      elements.resetPasswordMatchFeedback,
      elements.resetPasswordForm?.elements.new_password?.value,
      elements.resetPasswordForm?.elements.confirm_password?.value,
    );
  elements.resetPasswordForm?.elements.new_password?.addEventListener("input", updateResetPasswordMatch);
  elements.resetPasswordForm?.elements.confirm_password?.addEventListener("input", updateResetPasswordMatch);

  elements.resetPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const resetToken = currentResetToken();
    const form = new FormData(elements.resetPasswordForm);
    const newPassword = String(form.get("new_password") || "");
    const confirmPassword = String(form.get("confirm_password") || "");

    if (!resetToken) {
      const message = "Password reset link is missing. Request a new one.";
      showAuthFeedback(message, "error");
      setState({ message });
      return;
    }

    if (!updateResetPasswordMatch()) {
      const message = "Passwords do not match yet.";
      showAuthFeedback(message, "error");
      setState({ message });
      return;
    }

    try {
      setState({ message: "Saving new password..." });
      await requestJson("/api/auth/reset-password", {
        reset_token: resetToken,
        new_password: newPassword,
      });
      elements.resetPasswordForm.reset();
      clearPasswordMatchFeedback(elements.resetPasswordMatchFeedback);
      window.history.replaceState({}, "", "/account");
      setAuthMode("login", { preserveFeedback: true });
      showAuthFeedback("Password updated. You can log in now.", "success");
      setState({ message: "Password updated. You can log in now." });
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  elements.login2faForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.login2faForm);

    if (!pendingTwoFactorToken) {
      const message = "Start login again to request a new verification code.";
      showAuthFeedback(message, "error");
      setState({ message });
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
      hideAuthFeedback();
      elements.loginForm?.reset();
      await actions.refreshSession("Two-factor verification complete.");
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  elements.login2faResendButton?.addEventListener("click", async () => {
    if (!pendingTwoFactorToken) {
      const message = "Start login again to request a new verification code.";
      showAuthFeedback(message, "error");
      setState({ message });
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
      const message = `New verification code sent by ${
        session.two_factor_method === "sms" ? "SMS" : "email"
      }.`;
      showAuthFeedback(message, "success");
      setState({ message });
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  elements.login2faCancelButton?.addEventListener("click", () => {
    clearTwoFactorStep();
    setAuthMode("login");
    setState({ message: "Two-factor sign-in cancelled." });
  });

  const handleLogout = async () => {
    clearTwoFactorStep();
    hideAuthFeedback();
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
    hideAuthFeedback();
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
