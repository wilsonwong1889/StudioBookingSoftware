import { api } from "../api.js?v=20260401r";
import { STORAGE_KEYS } from "../config.js?v=20260401r";
import { elements, toggleHidden } from "../dom.js?v=20260401ab";
import { persistToken, setState } from "../state.js?v=20260401r";

let draftSaveTimer = null;
let lastHydratedFingerprint = null;
let activeDraftKey = null;
let lastDraftTimestamp = null;
let hasRestorableDraft = false;
let applyingDraft = false;

function asText(value) {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed || null;
}

function buildBillingAddress(form) {
  const address = {
    line1: asText(form.get("billing_line1")),
    line2: asText(form.get("billing_line2")),
    city: asText(form.get("billing_city")),
    state: asText(form.get("billing_state")),
    postal_code: asText(form.get("billing_postal_code")),
    country: asText(form.get("billing_country")),
  };

  return address.line1 ? address : null;
}

function buildProfilePayload() {
  const form = new FormData(elements.profileForm);
  return {
    full_name: asText(form.get("full_name")),
    phone: asText(form.get("phone")),
    birthday: asText(form.get("birthday")),
    billing_address: buildBillingAddress(form),
    opt_in_email: form.get("opt_in_email") === "on",
    opt_in_sms: form.get("opt_in_sms") === "on",
    two_factor_enabled: form.get("two_factor_enabled") === "on",
    two_factor_method: asText(form.get("two_factor_method")) || "email",
  };
}

function buildProfileSnapshot() {
  const payload = buildProfilePayload();
  return {
    ...payload,
    email: elements.profileForm.email.value || "",
  };
}

function applySnapshot(snapshot) {
  if (!elements.profileForm || !snapshot) {
    return;
  }

  applyingDraft = true;
  elements.profileForm.full_name.value = snapshot.full_name || "";
  elements.profileForm.email.value = snapshot.email || elements.profileForm.email.value || "";
  elements.profileForm.phone.value = snapshot.phone || "";
  elements.profileForm.birthday.value = snapshot.birthday || "";
  elements.profileForm.billing_line1.value = snapshot.billing_address?.line1 || "";
  elements.profileForm.billing_line2.value = snapshot.billing_address?.line2 || "";
  elements.profileForm.billing_city.value = snapshot.billing_address?.city || "";
  elements.profileForm.billing_state.value = snapshot.billing_address?.state || "";
  elements.profileForm.billing_postal_code.value = snapshot.billing_address?.postal_code || "";
  elements.profileForm.billing_country.value = snapshot.billing_address?.country || "";
  elements.profileForm.opt_in_email.checked = Boolean(snapshot.opt_in_email);
  elements.profileForm.opt_in_sms.checked = Boolean(snapshot.opt_in_sms);
  elements.profileForm.two_factor_enabled.checked = Boolean(snapshot.two_factor_enabled);
  elements.profileForm.two_factor_method.value = snapshot.two_factor_method || "email";
  applyingDraft = false;
}

function profileFingerprint(user) {
  return JSON.stringify({
    id: user.id,
    email: user.email,
    full_name: user.full_name,
    phone: user.phone,
    birthday: user.birthday,
    billing_address: user.billing_address,
    opt_in_email: user.opt_in_email,
    opt_in_sms: user.opt_in_sms,
    two_factor_enabled: user.two_factor_enabled,
    two_factor_method: user.two_factor_method,
    updated_at: user.updated_at,
  });
}

function getDraftKey(user) {
  const identifier = user?.id || user?.email || "anonymous";
  return `${STORAGE_KEYS.profileDraftPrefix}:${identifier}`;
}

function readDraft() {
  if (!activeDraftKey) {
    return null;
  }

  const raw = localStorage.getItem(activeDraftKey);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch (_error) {
    localStorage.removeItem(activeDraftKey);
    return null;
  }
}

function setSaveState(title, detail, { success = false, danger = false } = {}) {
  if (elements.profileSaveState) {
    elements.profileSaveState.textContent = title;
    elements.profileSaveState.classList.toggle("is-success", success);
    elements.profileSaveState.classList.toggle("is-error", danger);
  }
  if (elements.profileSaveDetail) {
    elements.profileSaveDetail.textContent = detail;
  }
}

function updateDraftControls() {
  toggleHidden(elements.profileRestoreDraftButton, !hasRestorableDraft);
  toggleHidden(elements.profileDiscardDraftButton, !hasRestorableDraft);
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "";
  }

  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function clearPasswordMatchFeedback() {
  if (!elements.profilePasswordMatchFeedback) {
    return;
  }
  elements.profilePasswordMatchFeedback.textContent = "";
  elements.profilePasswordMatchFeedback.classList.add("hidden");
  elements.profilePasswordMatchFeedback.classList.remove("is-match", "is-mismatch");
}

function updatePasswordMatchFeedback() {
  if (!elements.passwordForm || !elements.profilePasswordMatchFeedback) {
    return true;
  }

  const password = String(elements.passwordForm.elements.new_password?.value || "");
  const confirm = String(elements.passwordForm.elements.confirm_password?.value || "");

  if (!password && !confirm) {
    clearPasswordMatchFeedback();
    return true;
  }

  elements.profilePasswordMatchFeedback.classList.remove("hidden", "is-match", "is-mismatch");
  if (password && confirm && password === confirm) {
    elements.profilePasswordMatchFeedback.textContent = "Passwords match.";
    elements.profilePasswordMatchFeedback.classList.add("is-match");
    return true;
  }

  elements.profilePasswordMatchFeedback.textContent = "Passwords do not match.";
  elements.profilePasswordMatchFeedback.classList.add("is-mismatch");
  return false;
}

function clearDraft({ keepMessage = false } = {}) {
  if (draftSaveTimer) {
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = null;
  }

  if (activeDraftKey) {
    localStorage.removeItem(activeDraftKey);
  }

  hasRestorableDraft = false;
  lastDraftTimestamp = null;
  updateDraftControls();

  if (!keepMessage) {
    setSaveState("Account details are ready.", "You can save now or continue later.");
  }
}

function saveDraftNow() {
  if (!elements.profileForm || !activeDraftKey) {
    return;
  }

  const snapshot = buildProfileSnapshot();
  lastDraftTimestamp = new Date().toISOString();
  localStorage.setItem(
    activeDraftKey,
    JSON.stringify({
      saved_at: lastDraftTimestamp,
      snapshot,
    }),
  );
  hasRestorableDraft = true;
  updateDraftControls();
  setSaveState(
    "Draft saved locally.",
    `You can leave and continue later. Last draft: ${formatTimestamp(lastDraftTimestamp)}.`,
    { success: true },
  );
}

function scheduleDraftSave() {
  if (applyingDraft || !activeDraftKey) {
    return;
  }

  if (draftSaveTimer) {
    window.clearTimeout(draftSaveTimer);
  }

  setSaveState("Saving draft...", "Your changes are being saved locally.");
  draftSaveTimer = window.setTimeout(() => {
    saveDraftNow();
    draftSaveTimer = null;
  }, 250);
}

function hydrateFromUser(user) {
  applySnapshot({
    full_name: user.full_name,
    email: user.email,
    phone: user.phone,
    birthday: user.birthday,
    billing_address: user.billing_address,
    opt_in_email: user.opt_in_email,
    opt_in_sms: user.opt_in_sms,
    two_factor_enabled: user.two_factor_enabled,
    two_factor_method: user.two_factor_method,
  });
}

function restoreDraft() {
  const draft = readDraft();
  if (!draft?.snapshot) {
    hasRestorableDraft = false;
    updateDraftControls();
    return;
  }

  applySnapshot(draft.snapshot);
  lastDraftTimestamp = draft.saved_at || null;
  hasRestorableDraft = true;
  updateDraftControls();
  setSaveState(
    "Draft restored.",
    `Restored your local draft from ${formatTimestamp(lastDraftTimestamp)}.`,
    { success: true },
  );
}

export function initProfileView(actions) {
  if (!elements.profileForm || !elements.passwordForm) {
    return;
  }

  elements.profileForm.addEventListener("input", () => {
    scheduleDraftSave();
  });

  elements.profileForm.addEventListener("change", () => {
    scheduleDraftSave();
  });

  if (elements.profileRestoreDraftButton) {
    elements.profileRestoreDraftButton.addEventListener("click", () => {
      restoreDraft();
    });
  }

  if (elements.profileDiscardDraftButton) {
    elements.profileDiscardDraftButton.addEventListener("click", () => {
      clearDraft();
      setSaveState("Draft cleared.", "Local draft removed. Keep editing and save when ready.", {
        success: true,
      });
    });
  }

  elements.profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = buildProfilePayload();

    try {
      setSaveState("Saving profile...", "Writing your profile to the account.");
      if (elements.profileSaveButton) {
        elements.profileSaveButton.disabled = true;
      }
      const user = await api.updateProfile(payload);
      lastHydratedFingerprint = profileFingerprint(user);
      hydrateFromUser(user);
      clearDraft({ keepMessage: true });
      setSaveState("Profile saved.", "Your account details are now stored on the server.", {
        success: true,
      });
      setState({ currentUser: user, message: "Profile updated." });
    } catch (error) {
      setSaveState("Save failed.", error.message, { danger: true });
      setState({ message: error.message });
    } finally {
      if (elements.profileSaveButton) {
        elements.profileSaveButton.disabled = false;
      }
    }
  });

  elements.passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.passwordForm);
    if (!updatePasswordMatchFeedback()) {
      setState({ message: "Passwords do not match yet." });
      return;
    }
    const payload = {
      current_password: form.get("current_password"),
      new_password: form.get("new_password"),
    };

    try {
      await api.updatePassword(payload);
      elements.passwordForm.reset();
      clearPasswordMatchFeedback();
      setState({ message: "Password updated." });
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.passwordForm.elements.new_password?.addEventListener("input", updatePasswordMatchFeedback);
  elements.passwordForm.elements.confirm_password?.addEventListener("input", updatePasswordMatchFeedback);

  elements.profileDeleteButton?.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Delete this account? Your profile will be removed and you will be signed out immediately.",
    );
    if (!confirmed) {
      return;
    }

    const deletePassword = window.prompt("Enter your password to delete this account.");
    if (!deletePassword) {
      setState({ message: "Account deletion cancelled." });
      return;
    }

    try {
      elements.profileDeleteButton.disabled = true;
      setSaveState("Deleting account...", "Removing your profile and ending this session.", {
        danger: true,
      });
      await api.deleteProfile({ password: deletePassword });
      clearDraft({ keepMessage: true });
      persistToken(null);
      await actions.clearSession();
      setState({ message: "Account deleted." });
    } catch (error) {
      setSaveState("Delete failed.", error.message, { danger: true });
      setState({ message: error.message });
    } finally {
      elements.profileDeleteButton.disabled = false;
    }
  });
}

export function renderProfileView(state) {
  if (!elements.profileEmpty || !elements.profileForm || !elements.passwordForm) {
    return;
  }

  const user = state.currentUser;
  const isSessionRestoring = Boolean(state.token && !state.currentUser);
  const isVisible = Boolean(user);
  if (elements.accountProfilePanel) {
    toggleHidden(elements.accountProfilePanel, !isVisible);
  }
  toggleHidden(elements.profileEmpty, isVisible || isSessionRestoring);
  toggleHidden(elements.profileForm, !isVisible);
  toggleHidden(elements.passwordForm, !isVisible);
  toggleHidden(elements.accountDangerZone, !isVisible);

  if (!user) {
    activeDraftKey = null;
    lastHydratedFingerprint = null;
    hasRestorableDraft = false;
    lastDraftTimestamp = null;
    updateDraftControls();
    if (!isSessionRestoring) {
      setSaveState("Account details are ready.", "You can save now or continue later.");
    }
    clearPasswordMatchFeedback();
    return;
  }

  const fingerprint = profileFingerprint(user);
  const nextDraftKey = getDraftKey(user);
  const draftKeyChanged = activeDraftKey !== nextDraftKey;
  activeDraftKey = nextDraftKey;

  const draft = readDraft();
  hasRestorableDraft = Boolean(draft?.snapshot);
  lastDraftTimestamp = draft?.saved_at || null;
  updateDraftControls();

  if (draftKeyChanged || lastHydratedFingerprint !== fingerprint) {
    hydrateFromUser(user);
    lastHydratedFingerprint = fingerprint;

    if (draft?.snapshot) {
      applySnapshot(draft.snapshot);
      setSaveState(
        "Draft ready to continue.",
        `Local draft found from ${formatTimestamp(lastDraftTimestamp)}. You can keep editing or save now.`,
        { success: true },
      );
    } else {
      setSaveState("Profile loaded.", "Your saved account details are ready to edit.", {
        success: true,
      });
    }
  }
}
