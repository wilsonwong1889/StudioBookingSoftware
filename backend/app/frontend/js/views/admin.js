import { api } from "../api.js?v=20260401r";
import { elements } from "../dom.js?v=20260401x";
import { setState } from "../state.js?v=20260401r";

let editingStaffProfileId = null;
let activeAdminTab = "overview";
let selectedAdminScheduleDate = new Date().toISOString().slice(0, 10);
let selectedAdminScheduleRoomId = "all";
let selectedAdminAccountId = null;
let adminSearchResults = null;

const TEST_CASE_HEALTH_META = {
  working: {
    label: "Working",
    className: "test-health-working",
    sortOrder: 2,
  },
  needs_fix: {
    label: "Needs fix",
    className: "test-health-needs-fix",
    sortOrder: 1,
  },
  not_working: {
    label: "Not working",
    className: "test-health-not-working",
    sortOrder: 0,
  },
};

function setActiveAdminTab(tab) {
  activeAdminTab = tab;
  elements.adminTabs?.forEach((button) => {
    button.classList.toggle("active", button.dataset.adminTab === tab);
    button.setAttribute("aria-selected", button.dataset.adminTab === tab ? "true" : "false");
  });
  elements.adminPanels?.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.adminPanel !== tab);
  });
  if (elements.adminWorkspaceSelect && elements.adminWorkspaceSelect.value !== tab) {
    elements.adminWorkspaceSelect.value = tab;
  }
}

function toIsoStringFromLocal(value) {
  const localDate = new Date(value);
  return localDate.toISOString();
}

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDateOnly(value) {
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatTimeOnly(value) {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function renderManualDurationOptions(currentState) {
  if (!elements.adminManualBookingForm || !elements.adminRoomSelect) {
    return;
  }

  const durationSelect = elements.adminManualBookingForm.elements.duration_minutes;
  if (!durationSelect) {
    return;
  }

  const room = (currentState.rooms || []).find((item) => String(item.id) === elements.adminRoomSelect.value);
  const maxDuration = room?.max_booking_duration_minutes || 300;
  const previousValue = Number(durationSelect.value || 60);
  const options = [];
  for (let duration = 60; duration <= maxDuration; duration += 60) {
    options.push(`<option value="${duration}">${formatDuration(duration)}</option>`);
  }
  durationSelect.innerHTML = options.join("");
  durationSelect.value = options.some((_option, index) => (index + 1) * 60 === previousValue)
    ? String(previousValue)
    : "60";
}

function formatPhone(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return value || "No phone";
}

function getDateKey(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function getStatusClass(status) {
  return `status-${String(status || "").toLowerCase()}`;
}

function formatMoney(cents, currency = "CAD") {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format((cents || 0) / 100);
}

function formatActivityAction(action) {
  return action.replaceAll("_", " ");
}

function normalizeTestCaseHealth(health) {
  return String(health || "working")
    .trim()
    .toLowerCase()
    .replaceAll(" ", "_")
    .replaceAll("-", "_");
}

function getTestCaseHealthMeta(health) {
  return TEST_CASE_HEALTH_META[normalizeTestCaseHealth(health)] || TEST_CASE_HEALTH_META.working;
}

function getActiveRooms(rooms) {
  return (rooms || []).filter((room) => room.active);
}

function parseListInput(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderStaffImage(photoUrl, label, className = "staff-avatar") {
  if (photoUrl) {
    return `<img class="${className}" src="${photoUrl}" alt="${label}" loading="lazy" />`;
  }
  return `<div class="${className} staff-avatar-fallback">${label.slice(0, 1).toUpperCase()}</div>`;
}

function setStaffPhotoPreview(photoUrl, name = "Staff member") {
  if (!elements.adminStaffPhotoPreview) {
    return;
  }

  elements.adminStaffPhotoPreview.innerHTML = photoUrl
    ? `
        <div class="staff-photo-preview-card">
          ${renderStaffImage(photoUrl, name, "staff-photo-preview-image")}
          <div class="staff-option-copy">
            <strong>${name}</strong>
            <span>Current profile image saved for this staff profile.</span>
          </div>
        </div>
      `
    : "Upload a JPG photo to show this staff member on room and booking pages.";
  elements.adminStaffPhotoPreview.classList.toggle("empty-state", !photoUrl);
}

function resetStaffProfileForm() {
  editingStaffProfileId = null;
  elements.adminStaffProfileForm?.reset();
  if (elements.adminStaffProfileId) {
    elements.adminStaffProfileId.value = "";
  }
  if (elements.adminStaffPhotoUrl) {
    elements.adminStaffPhotoUrl.value = "";
  }
  if (elements.adminStaffPhotoFile) {
    elements.adminStaffPhotoFile.value = "";
  }
  const activeCheckbox = elements.adminStaffProfileForm?.querySelector("input[name='active']");
  if (activeCheckbox) {
    activeCheckbox.checked = true;
  }
  setStaffPhotoPreview(null);
}

function populateStaffProfileForm(profile) {
  if (!elements.adminStaffProfileForm) {
    return;
  }

  editingStaffProfileId = profile.id;
  elements.adminStaffProfileForm.elements.name.value = profile.name || "";
  elements.adminStaffProfileForm.elements.description.value = profile.description || "";
  elements.adminStaffProfileForm.elements.skills.value = (profile.skills || []).join(", ");
  elements.adminStaffProfileForm.elements.talents.value = (profile.talents || []).join(", ");
  elements.adminStaffProfileForm.elements.add_on_price_cents.value = profile.add_on_price_cents || 0;
  elements.adminStaffProfileForm.elements.active.checked = Boolean(profile.active);
  if (elements.adminStaffProfileId) {
    elements.adminStaffProfileId.value = profile.id;
  }
  if (elements.adminStaffPhotoUrl) {
    elements.adminStaffPhotoUrl.value = profile.photo_url || "";
  }
  if (elements.adminStaffPhotoFile) {
    elements.adminStaffPhotoFile.value = "";
  }
  setStaffPhotoPreview(profile.photo_url, profile.name);
}

function getSelectedManualStaffIds() {
  if (!elements.adminManualStaffOptions) {
    return [];
  }

  return Array.from(
    elements.adminManualStaffOptions.querySelectorAll("input[type='checkbox']:checked"),
  ).map((input) => input.value);
}

function renderStaffTagRow(label, values = []) {
  if (!values.length) {
    return "";
  }

  return `
    <div class="staff-tag-group">
      <span>${label}</span>
      <div class="preview-pill-row">
        ${values.map((value) => `<span class="pill">${value}</span>`).join("")}
      </div>
    </div>
  `;
}

function formatAddress(address) {
  if (!address) {
    return "No billing address";
  }

  return [
    address.line1,
    address.line2,
    [address.city, address.state].filter(Boolean).join(", "),
    [address.postal_code, address.country].filter(Boolean).join(" "),
  ]
    .filter(Boolean)
    .join("<br />");
}

function renderAccountField(label, value, { mono = false } = {}) {
  return `
    <div class="admin-detail-field${mono ? " is-mono" : ""}">
      <span>${label}</span>
      <div class="admin-detail-value">${value || "Not provided"}</div>
    </div>
  `;
}

function renderAdminAccountListItem(account, isSelected) {
  return `
    <button class="admin-account-list-item${isSelected ? " is-selected" : ""}" type="button" data-admin-action="select-account" data-user-id="${account.id}">
      <div class="admin-account-list-top">
        <strong>${account.full_name || account.email}</strong>
        <span>${account.email}</span>
      </div>
      <div class="room-meta">
        <span class="pill">${account.is_admin ? "Admin" : "Customer"}</span>
        <span class="pill">${account.booking_count} booking${account.booking_count === 1 ? "" : "s"}</span>
      </div>
      <p>${account.phone ? formatPhone(account.phone) : "No phone on file"}</p>
      <p>${account.billing_address ? "Billing address on file" : "No billing address on file"}</p>
    </button>
  `;
}

function renderAdminAccountDetail(account, currentUser) {
  const isCurrentUser = String(account.id) === String(currentUser?.id || "");
  const deleteControl = isCurrentUser
    ? `
        <button class="ghost-button" type="button" disabled>Signed in on this account</button>
        <p class="field-help">Delete your own profile from the account page so this admin session can close cleanly.</p>
      `
    : `
        <button class="ghost-button room-action-danger" type="button" data-admin-action="delete-user-account" data-user-id="${account.id}" data-user-email="${account.email}">
          Delete account
        </button>
      `;

  return `
    <article class="admin-account-detail-card">
      <div class="admin-account-detail-header">
        <div>
          <h4>${account.full_name || account.email}</h4>
          <p>${account.email}</p>
        </div>
        <div class="room-meta">
          <span class="pill">${account.is_admin ? "Admin" : "Customer"}</span>
          <span class="pill">${account.opt_in_email ? "Email opt-in" : "Email opt-out"}</span>
          <span class="pill">${account.opt_in_sms ? "SMS opt-in" : "SMS opt-out"}</span>
        </div>
      </div>

      <div class="admin-account-stats">
        <article class="metric-card">
          <span class="metric-label">Bookings</span>
          <strong class="metric-value">${account.booking_count}</strong>
        </article>
        <article class="metric-card">
          <span class="metric-label">Last booking</span>
          <strong class="metric-value metric-value-small">${account.last_booking_at ? formatBookingDate(account.last_booking_at) : "No bookings yet"}</strong>
        </article>
      </div>

      <section class="admin-account-section">
        <h4>Personal details</h4>
        <div class="admin-detail-grid">
          ${renderAccountField("Full name", account.full_name || "Not provided")}
          ${renderAccountField("Email", account.email, { mono: true })}
          ${renderAccountField("Phone", account.phone ? formatPhone(account.phone) : "No phone on file")}
          ${renderAccountField("Birthday", account.birthday ? formatDateOnly(account.birthday) : "Not provided")}
        </div>
      </section>

      <section class="admin-account-section">
        <h4>Billing</h4>
        <p class="field-help">Card details are handled by Stripe and are not stored in this app.</p>
        <div class="admin-detail-grid">
          ${renderAccountField("Billing address", formatAddress(account.billing_address))}
        </div>
      </section>

      <section class="admin-account-section">
        <h4>Account lifecycle</h4>
        <div class="admin-detail-grid">
          ${renderAccountField("Created", formatBookingDate(account.created_at))}
          ${renderAccountField("Updated", account.updated_at ? formatBookingDate(account.updated_at) : "No later updates")}
        </div>
      </section>

      <div class="room-actions">
        ${deleteControl}
      </div>
    </article>
  `;
}

function renderAdminTestCaseCard(testCase) {
  const healthMeta = getTestCaseHealthMeta(testCase.health);
  const commands = testCase.commands || [];
  return `
    <article class="admin-test-case-card ${healthMeta.className}">
      <div class="admin-test-case-header">
        <div>
          <h4>${testCase.title}</h4>
          <p>${testCase.summary}</p>
        </div>
        <div class="room-meta">
          <span class="pill test-health-pill ${healthMeta.className}">
            <span class="test-status-light ${healthMeta.className}"></span>
            ${healthMeta.label}
          </span>
          <span class="pill">${testCase.area}</span>
          <span class="pill">${testCase.status}</span>
        </div>
      </div>
      <div class="admin-detail-grid">
        <div class="admin-detail-field is-mono">
          <span>Source file</span>
          <div class="admin-detail-value">${testCase.source_file}</div>
        </div>
        <div class="admin-detail-field is-mono">
          <span>Test id</span>
          <div class="admin-detail-value">${testCase.source_test}</div>
        </div>
      </div>
      <div class="admin-test-case-section">
        <span>Covered paths</span>
        <div class="preview-pill-row">
          ${(testCase.covered_paths || []).map((path) => `<span class="pill">${path}</span>`).join("")}
        </div>
      </div>
      <div class="admin-test-case-section">
        <span>Run command</span>
        ${commands.length
          ? commands
          .map(
            (command) => `
              <div class="admin-detail-field is-mono">
                <div class="admin-detail-value">${command}</div>
              </div>
            `,
          )
          .join("")
          : `
              <div class="admin-detail-field">
                <div class="admin-detail-value">No automated command is registered for this case yet.</div>
              </div>
            `}
      </div>
    </article>
  `;
}

function renderAdminTestCaseSummary(testCases) {
  if (!elements.adminTestCaseSummary) {
    return;
  }

  const counts = {
    working: 0,
    needs_fix: 0,
    not_working: 0,
  };

  for (const testCase of testCases) {
    const health = normalizeTestCaseHealth(testCase.health);
    if (Object.hasOwn(counts, health)) {
      counts[health] += 1;
    }
  }

  const cards = [
    {
      label: "Working",
      value: counts.working,
      className: "test-health-working",
      description: "Covered backend cases that are passing.",
    },
    {
      label: "Needs fix",
      value: counts.needs_fix,
      className: "test-health-needs-fix",
      description: "Cases that still need follow-up work.",
    },
    {
      label: "Not working",
      value: counts.not_working,
      className: "test-health-not-working",
      description: "Cases marked broken or still missing.",
    },
    {
      label: "Total cases",
      value: testCases.length,
      className: "test-health-total",
      description: "All backend test cases tracked in this dashboard.",
    },
  ];

  elements.adminTestCaseSummary.innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card test-status-card ${card.className}">
          <div class="room-meta">
            <span class="test-status-light ${card.className}"></span>
            <span class="metric-label">${card.label}</span>
          </div>
          <strong class="metric-value">${card.value}</strong>
          <span class="status-detail">${card.description}</span>
        </article>
      `,
    )
    .join("");
}

function renderManualBookingStaffOptions(currentState) {
  if (!elements.adminManualStaffSection || !elements.adminManualStaffOptions || !elements.adminRoomSelect) {
    return;
  }

  const room = (currentState.rooms || []).find((item) => String(item.id) === elements.adminRoomSelect.value);
  const staffRoles = room?.staff_roles || [];
  const selectedIds = new Set(getSelectedManualStaffIds());

  if (!staffRoles.length) {
    elements.adminManualStaffOptions.innerHTML = "";
    elements.adminManualStaffSection.classList.add("hidden");
    return;
  }

  elements.adminManualStaffSection.classList.remove("hidden");
  elements.adminManualStaffOptions.innerHTML = staffRoles
    .map(
      (role) => `
        <label class="staff-option-card staff-option-card-compact">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${role.id}" ${selectedIds.has(role.id) ? "checked" : ""} />
          </div>
          ${renderStaffImage(role.photo_url, role.name)}
          <div class="staff-option-copy">
            <strong>${role.name}</strong>
            <span>${role.description || "Optional booking add-on."}</span>
            ${renderStaffTagRow("Skills", role.skills || [])}
          </div>
          <strong class="staff-option-price">${formatMoney(role.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function renderAdminBookingCard(booking) {
  const refundButton =
    booking.price_cents > 0 &&
    (booking.status === "Paid" || booking.status === "Cancelled" || booking.status === "Completed")
      ? `<button class="ghost-button admin-booking-action" type="button" data-admin-action="refund" data-booking-id="${booking.id}" data-amount="${booking.price_cents}">Refund</button>`
      : "";
  const waivePaymentButton =
    booking.status === "PendingPayment"
      ? `<button class="ghost-button admin-booking-action" type="button" data-admin-action="waive-payment" data-booking-id="${booking.id}">Skip Stripe and mark free</button>`
      : "";
  const checkInButton =
    booking.status === "Paid" && !booking.checked_in_at
      ? `<button class="primary-button admin-booking-action" type="button" data-admin-action="check-in" data-booking-id="${booking.id}">Mark arrived</button>`
      : "";
  const staffAssignments = booking.staff_assignments || [];
  const guestName = booking.user_full_name || "Guest name not set";
  const guestPhone = booking.user_phone ? formatPhone(booking.user_phone) : "No phone";

  return `
    <article class="booking-card admin-booking-record ${getStatusClass(booking.status)}">
      <div class="admin-booking-header">
        <div>
          <h4>${booking.room_name || "Room"} • ${booking.booking_code}</h4>
          <p>${formatBookingDate(booking.start_time)} to ${formatBookingDate(booking.end_time)}</p>
        </div>
        <div class="room-meta">
          <span class="pill ${getStatusClass(booking.status)}">${booking.status}</span>
          <span class="pill">${formatDuration(booking.duration_minutes)}</span>
          <span class="pill">${formatMoney(booking.price_cents, booking.currency)}</span>
        </div>
      </div>
      <div class="admin-booking-detail-grid">
        <div class="availability-preview">
          <span class="availability-label">Guest</span>
          <p><strong>${guestName}</strong></p>
          <p>${booking.user_email || "No email"}</p>
          <p>${guestPhone}</p>
        </div>
        <div class="availability-preview">
          <span class="availability-label">Booking status</span>
          <p>${booking.status}</p>
          <p>${booking.created_at ? `Booked at ${formatBookingDate(booking.created_at)}` : "Booking time unavailable"}</p>
          <p>${booking.checked_in_at ? `Checked in ${formatBookingDate(booking.checked_in_at)}` : "Not checked in yet"}</p>
          <p>${booking.cancelled_at ? `Cancelled ${formatBookingDate(booking.cancelled_at)}` : "Active or completed booking"}</p>
        </div>
      </div>
      ${staffAssignments.length ? `<p><strong>Staff:</strong> ${staffAssignments.map((assignment) => assignment.name).join(", ")}</p>` : '<p><strong>Staff:</strong> None attached</p>'}
      ${booking.cancellation_reason ? `<p><strong>Cancellation reason:</strong> ${booking.cancellation_reason}</p>` : ""}
      ${booking.note ? `<p><strong>Notes:</strong> ${booking.note}</p>` : ""}
      ${(waivePaymentButton || checkInButton || refundButton) ? `<div class="room-actions">${waivePaymentButton}${checkInButton}${refundButton}</div>` : ""}
    </article>
  `;
}

function getFilteredScheduleBookings(currentState) {
  return (currentState.adminBookings || [])
    .filter((booking) => getDateKey(booking.start_time) === selectedAdminScheduleDate)
    .filter((booking) => selectedAdminScheduleRoomId === "all" || String(booking.room_id) === selectedAdminScheduleRoomId)
    .sort((left, right) => new Date(left.start_time).getTime() - new Date(right.start_time).getTime());
}

function renderAdminDaySummary(currentState) {
  if (!elements.adminDaySummary) {
    return;
  }

  const bookings = getFilteredScheduleBookings(currentState);
  const activeStatuses = new Set(["PendingPayment", "Paid", "Completed"]);
  const activeCount = bookings.filter((booking) => activeStatuses.has(booking.status)).length;
  const cancelledCount = bookings.filter((booking) => ["Cancelled", "Refunded"].includes(booking.status)).length;
  const guestCount = new Set(bookings.map((booking) => booking.user_email || booking.user_id || booking.id)).size;
  const revenue = bookings
    .filter((booking) => ["Paid", "Completed", "Refunded"].includes(booking.status))
    .reduce((total, booking) => total + (booking.price_cents || 0), 0);
  const cards = [
    { label: "Bookings on this day", value: bookings.length },
    { label: "Active sessions", value: activeCount },
    { label: "Cancelled or refunded", value: cancelledCount },
    { label: "Guests", value: guestCount },
    { label: "Booked revenue", value: formatMoney(revenue) },
  ];

  elements.adminDaySummary.innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card">
          <span class="metric-label">${card.label}</span>
          <strong class="metric-value">${card.value}</strong>
        </article>
      `,
    )
    .join("");
}

function renderScheduleBlocks(bookings) {
  return bookings
    .map((booking) => {
      const start = new Date(booking.start_time);
      const end = new Date(booking.end_time);
      const startMinutes = start.getHours() * 60 + start.getMinutes();
      const endMinutes = end.getHours() * 60 + end.getMinutes();
      const businessStart = 10 * 60;
      const businessEnd = 18 * 60;
      const clampedStart = Math.max(startMinutes, businessStart);
      const clampedEnd = Math.min(endMinutes, businessEnd);
      const width = Math.max(((clampedEnd - clampedStart) / (businessEnd - businessStart)) * 100, 10);
      const left = ((clampedStart - businessStart) / (businessEnd - businessStart)) * 100;
      const guestLabel = booking.user_full_name || booking.user_email || "Guest";
      return `
        <article class="admin-schedule-block ${getStatusClass(booking.status)}" style="left:${left}%;width:${width}%;">
          <strong>${formatTimeOnly(booking.start_time)} to ${formatTimeOnly(booking.end_time)}</strong>
          <span>${guestLabel}</span>
          <span>${booking.status}</span>
        </article>
      `;
    })
    .join("");
}

function renderAdminDaySchedule(currentState) {
  if (!elements.adminDaySchedule) {
    return;
  }

  const bookings = getFilteredScheduleBookings(currentState);
  const rooms = (currentState.rooms || [])
    .filter((room) => selectedAdminScheduleRoomId === "all" || String(room.id) === selectedAdminScheduleRoomId)
    .sort((left, right) => left.name.localeCompare(right.name));
  const hourLabels = Array.from({ length: 8 }, (_value, index) => 10 + index);

  if (!rooms.length) {
    elements.adminDaySchedule.innerHTML = '<div class="empty-state">No rooms match the selected filter.</div>';
    return;
  }

  elements.adminDaySchedule.innerHTML = `
    <div class="admin-schedule-hours">
      <div></div>
      <div class="admin-schedule-hour-track">
        ${hourLabels
          .map((hour) => `<span>${new Intl.DateTimeFormat("en-US", { hour: "numeric" }).format(new Date(`2026-04-01T${String(hour).padStart(2, "0")}:00:00`))}</span>`)
          .join("")}
      </div>
    </div>
    ${
      rooms
        .map((room) => {
          const roomBookings = bookings.filter((booking) => String(booking.room_id) === String(room.id));
          return `
            <article class="admin-day-row">
              <div class="admin-day-room">
                <strong>${room.name}</strong>
                <span>${roomBookings.length} booking${roomBookings.length === 1 ? "" : "s"}</span>
              </div>
              <div class="admin-day-track">
                <div class="admin-day-grid">
                  ${hourLabels.map(() => '<span></span>').join("")}
                </div>
                ${roomBookings.length ? renderScheduleBlocks(roomBookings) : '<div class="admin-day-empty">No bookings in this room for the selected day.</div>'}
              </div>
            </article>
          `;
        })
        .join("")
    }
  `;
}

function renderStaffCatalogCard(profile) {
  return `
    <article class="staff-profile-card">
      <div class="staff-profile-card-top">
        ${renderStaffImage(profile.photo_url, profile.name, "staff-profile-image")}
        <div class="staff-option-copy">
          <strong>${profile.name}</strong>
          <span>${profile.description || "No profile summary added yet."}</span>
        </div>
      </div>
      <div class="room-meta">
        <span class="pill">${formatMoney(profile.add_on_price_cents)}</span>
        <span class="pill ${profile.active ? "" : "muted"}">${profile.active ? "Active" : "Inactive"}</span>
      </div>
      ${renderStaffTagRow("Skills", profile.skills || [])}
      ${renderStaffTagRow("Talents", profile.talents || [])}
      <div class="room-actions">
        <button class="ghost-button" type="button" data-admin-action="edit-staff-profile" data-staff-profile-id="${profile.id}">Edit profile</button>
        <button class="ghost-button" type="button" data-admin-action="toggle-staff-profile" data-staff-profile-id="${profile.id}" data-next-active="${profile.active ? "false" : "true"}">${profile.active ? "Deactivate" : "Activate"}</button>
        <button class="ghost-button room-action-danger" type="button" data-admin-action="delete-staff-profile" data-staff-profile-id="${profile.id}" data-staff-profile-name="${profile.name}">Delete</button>
      </div>
    </article>
  `;
}

function renderRoomStaffAssignmentCard(room, staffProfiles) {
  const assignedIds = new Set((room.staff_roles || []).map((role) => role.id));
  const availableProfiles = (staffProfiles || []).filter((profile) => profile.active || assignedIds.has(profile.id));

  return `
    <article class="admin-room-staff-card" data-room-card data-room-id="${room.id}">
      <header class="admin-room-staff-header">
        <div>
          <h4>${room.name}</h4>
          <p>${room.description || "No description"}</p>
        </div>
        <div class="room-meta">
          <span class="pill">${formatMoney(room.hourly_rate_cents)}/hour</span>
          <span class="pill">${assignedIds.size} assigned staff profile${assignedIds.size === 1 ? "" : "s"}</span>
        </div>
      </header>
      <div class="staff-assignment-grid">
        ${availableProfiles.length
          ? availableProfiles
              .map(
                (profile) => `
                  <label class="staff-option-card staff-option-card-compact">
                    <div class="staff-option-toggle">
                      <input type="checkbox" value="${profile.id}" ${assignedIds.has(profile.id) ? "checked" : ""} />
                    </div>
                    ${renderStaffImage(profile.photo_url, profile.name)}
                    <div class="staff-option-copy">
                      <strong>${profile.name}</strong>
                      <span>${profile.description || "No summary added yet."}</span>
                    </div>
                    <strong class="staff-option-price">${formatMoney(profile.add_on_price_cents)}</strong>
                  </label>
                `,
              )
              .join("")
          : '<div class="empty-state">Create staff profiles above before assigning anyone to a room.</div>'}
      </div>
      <div class="room-actions">
        <button class="primary-button" type="button" data-admin-action="save-room-staff" data-room-id="${room.id}">Save room staff</button>
      </div>
    </article>
  `;
}

function collectRoomStaffPayload(roomCard, staffProfiles) {
  const selectedIds = Array.from(
    roomCard.querySelectorAll("input[type='checkbox']:checked"),
  ).map((input) => input.value);
  const byId = new Map((staffProfiles || []).map((profile) => [String(profile.id), profile]));

  return selectedIds.flatMap((staffProfileId) => {
    const profile = byId.get(staffProfileId);
    if (!profile) {
      return [];
    }
    return [
      {
        id: String(profile.id),
        name: profile.name,
        description: profile.description || null,
        add_on_price_cents: profile.add_on_price_cents || 0,
        photo_url: profile.photo_url || null,
        skills: profile.skills || [],
        talents: profile.talents || [],
      },
    ];
  });
}

export function initAdminView(actions) {
  if (
    !elements.adminEmpty ||
    !elements.adminBookingLookupForm ||
    !elements.adminBookingResults ||
    !elements.adminManualBookingForm ||
    !elements.adminRoomSelect
  ) {
    return;
  }

  elements.adminBookingLookupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.adminBookingLookupForm);
    try {
      setState({ message: "Searching bookings..." });
      adminSearchResults = await api.adminLookupBookings({
        email: form.get("email"),
        booking_code: form.get("booking_code"),
        status: form.get("status"),
      });
      renderAdminView(actions.getState());
      setState({ message: "Admin booking results loaded." });
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminBookingClearButton?.addEventListener("click", () => {
      adminSearchResults = null;
      elements.adminBookingLookupForm?.reset();
      renderAdminView(actions.getState());
      setState({ message: "Booking filters cleared." });
  });

  elements.adminRoomSelect?.addEventListener("change", () => {
    renderManualDurationOptions(actions.getState());
    renderManualBookingStaffOptions(actions.getState());
  });

  elements.adminScheduleDate?.addEventListener("change", () => {
    selectedAdminScheduleDate = elements.adminScheduleDate.value || todayString();
    renderAdminView(actions.getState());
  });

  elements.adminScheduleRoomFilter?.addEventListener("change", () => {
    selectedAdminScheduleRoomId = elements.adminScheduleRoomFilter.value || "all";
    renderAdminView(actions.getState());
  });

  elements.adminClearDayButton?.addEventListener("click", async () => {
    const targetDate = elements.adminScheduleDate?.value || selectedAdminScheduleDate;
    if (!targetDate) {
      setState({ message: "Choose a day first." });
      return;
    }
    const confirmed = window.confirm(`Delete all bookings on ${targetDate}? This permanently removes them.`);
    if (!confirmed) {
      return;
    }

    try {
      setState({ message: "Clearing bookings for selected day..." });
      const result = await api.adminClearBookingsForDay({ date: targetDate });
      adminSearchResults = null;
      await actions.refreshAll(`${result.deleted_count} booking${result.deleted_count === 1 ? "" : "s"} cleared for ${targetDate}.`);
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminClearPastButton?.addEventListener("click", async () => {
    const confirmed = window.confirm("Delete all past bookings? This permanently removes every booking before now.");
    if (!confirmed) {
      return;
    }

    try {
      setState({ message: "Clearing past bookings..." });
      const result = await api.adminClearPastBookings();
      adminSearchResults = null;
      await actions.refreshAll(`${result.deleted_count} past booking${result.deleted_count === 1 ? "" : "s"} cleared.`);
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminTabs?.forEach((button) => {
    button.addEventListener("click", () => {
      setActiveAdminTab(button.dataset.adminTab);
    });
  });

  elements.adminWorkspaceSelect?.addEventListener("change", () => {
    setActiveAdminTab(elements.adminWorkspaceSelect.value || "overview");
  });

  elements.adminAccountsList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-action='select-account']");
    if (!button) {
      return;
    }

    selectedAdminAccountId = button.dataset.userId;
    renderAdminView(actions.getState());
  });

  elements.adminAccountDetail?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action='delete-user-account']");
    if (!button) {
      return;
    }

    const accountEmail = button.dataset.userEmail || "this account";
    const confirmed = window.confirm(`Delete ${accountEmail}? This removes the profile from the system.`);
    if (!confirmed) {
      return;
    }

    try {
      setState({ message: "Deleting account..." });
      await api.adminDeleteUser(button.dataset.userId);
      if (selectedAdminAccountId === button.dataset.userId) {
        selectedAdminAccountId = null;
      }
      await actions.refreshAll("Account deleted.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminStaffPhotoFile?.addEventListener("change", () => {
    const file = elements.adminStaffPhotoFile.files?.[0];
    if (!file) {
      const name = elements.adminStaffProfileForm?.elements?.name?.value || "Staff member";
      setStaffPhotoPreview(elements.adminStaffPhotoUrl?.value || null, name);
      return;
    }
    setStaffPhotoPreview(URL.createObjectURL(file), elements.adminStaffProfileForm?.elements?.name?.value || file.name);
  });

  elements.adminStaffCancelEdit?.addEventListener("click", () => {
    resetStaffProfileForm();
  });

  elements.adminStaffProfileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = elements.adminStaffProfileForm;
    const file = elements.adminStaffPhotoFile?.files?.[0];

    try {
      setState({ message: editingStaffProfileId ? "Updating staff profile..." : "Creating staff profile..." });
      let photoUrl = elements.adminStaffPhotoUrl?.value || null;
      if (file) {
        const upload = await api.adminUploadStaffPhoto(file);
        photoUrl = upload.photo_url;
      }

      const payload = {
        name: form.elements.name.value.trim(),
        description: form.elements.description.value.trim() || null,
        skills: parseListInput(form.elements.skills.value),
        talents: parseListInput(form.elements.talents.value),
        photo_url: photoUrl,
        add_on_price_cents: Number(form.elements.add_on_price_cents.value || 0),
        active: form.elements.active.checked,
      };

      if (editingStaffProfileId) {
        await api.adminUpdateStaffProfile(editingStaffProfileId, payload);
      } else {
        await api.adminCreateStaffProfile(payload);
      }

      resetStaffProfileForm();
      await actions.refreshAll("Staff profile saved.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminManualBookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.adminManualBookingForm);
    try {
      setState({ message: "Creating manual booking..." });
      await api.adminCreateManualBooking({
        user_email: form.get("user_email"),
        full_name: form.get("full_name") || null,
        room_id: form.get("room_id"),
        start_time: toIsoStringFromLocal(form.get("start_time")),
        duration_minutes: Number(form.get("duration_minutes")),
        note: form.get("note") || null,
        staff_assignments: getSelectedManualStaffIds(),
      });
      elements.adminManualBookingForm.reset();
      if (elements.adminBookingStart) {
        elements.adminBookingStart.value = "";
      }
      adminSearchResults = null;
      renderManualBookingStaffOptions(actions.getState());
      await actions.refreshAll("Manual booking created.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminBookingResults.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action]");
    if (!button) {
      return;
    }

    try {
      if (button.dataset.adminAction === "waive-payment") {
        const confirmed = window.confirm("Skip Stripe and mark this booking free?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Marking booking free..." });
        await api.adminWaiveBookingPayment(button.dataset.bookingId);
        adminSearchResults = null;
        await actions.refreshAll("Booking marked paid without Stripe.");
        return;
      }

      if (button.dataset.adminAction === "refund") {
        setState({ message: "Processing refund..." });
        await api.adminRefundBooking(button.dataset.bookingId, {
          amount_cents: Number(button.dataset.amount),
          reason: "Admin refund",
        });
        adminSearchResults = null;
        await actions.refreshAll("Refund processed.");
        return;
      }

      if (button.dataset.adminAction === "check-in") {
        setState({ message: "Marking guest as arrived..." });
        await api.adminCheckInBooking(button.dataset.bookingId);
        adminSearchResults = null;
        await actions.refreshAll("Guest checked in.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminStaffCatalogList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action]");
    if (!button) {
      return;
    }

    const currentState = actions.getState();
    const profile = (currentState.adminStaffProfiles || []).find((item) => String(item.id) === button.dataset.staffProfileId);

    try {
      if (button.dataset.adminAction === "edit-staff-profile") {
        if (!profile) {
          setState({ message: "Staff profile not found." });
          return;
        }
        populateStaffProfileForm(profile);
        setState({ message: `Editing ${profile.name}.` });
        return;
      }

      if (button.dataset.adminAction === "toggle-staff-profile") {
        if (!profile) {
          setState({ message: "Staff profile not found." });
          return;
        }
        const nextActive = button.dataset.nextActive === "true";
        setState({ message: nextActive ? "Activating staff profile..." : "Deactivating staff profile..." });
        await api.adminUpdateStaffProfile(profile.id, { active: nextActive });
        await actions.refreshAll(nextActive ? "Staff profile activated." : "Staff profile deactivated.");
        return;
      }

      if (button.dataset.adminAction === "delete-staff-profile") {
        const profileName = button.dataset.staffProfileName || "this staff profile";
        const confirmed = window.confirm(`Delete ${profileName}? This will also remove the profile from any rooms.`);
        if (!confirmed) {
          return;
        }
        setState({ message: "Deleting staff profile..." });
        await api.adminDeleteStaffProfile(button.dataset.staffProfileId);
        resetStaffProfileForm();
        await actions.refreshAll("Staff profile deleted.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminRoomStaffList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action='save-room-staff']");
    if (!button) {
      return;
    }

    const roomCard = button.closest("[data-room-card]");
    if (!roomCard) {
      return;
    }

    try {
      const currentState = actions.getState();
      const roomId = button.dataset.roomId;
      const staffRoles = collectRoomStaffPayload(roomCard, currentState.adminStaffProfiles);
      setState({ message: "Saving room staff..." });
      await api.adminUpdateRoom(roomId, { staff_roles: staffRoles });
      await actions.refreshAll("Room staff updated.");
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

export function renderAdminView(currentState) {
  if (
    !elements.adminEmpty ||
    !elements.adminBookingLookupForm ||
    !elements.adminBookingResults ||
    !elements.adminManualBookingForm ||
    !elements.adminRoomSelect
  ) {
    return;
  }

  const isAdmin = Boolean(currentState.currentUser?.is_admin);
  elements.adminEmpty.classList.toggle("hidden", isAdmin);
  elements.adminWorkspaceShell?.classList.toggle("hidden", !isAdmin);
  elements.adminAnalyticsPanel?.classList.toggle("hidden", !isAdmin);
  elements.adminActivityPanel?.classList.toggle("hidden", !isAdmin);
  elements.adminBookingLookupForm.classList.toggle("hidden", !isAdmin);
  elements.adminManualBookingForm.classList.toggle("hidden", !isAdmin);
  elements.adminStaffProfileForm?.classList.toggle("hidden", !isAdmin);
  elements.adminBookingResults.classList.toggle("hidden", !isAdmin);
  elements.adminRoomManagementPanel?.classList.toggle("hidden", !isAdmin);

  const activeRooms = getActiveRooms(currentState.rooms);
  const roomOptions = activeRooms.map(
    (room) => `<option value="${room.id}">${room.name}</option>`,
  );
  const previousRoomId = elements.adminRoomSelect.value;
  const previousScheduleRoomId = elements.adminScheduleRoomFilter?.value || selectedAdminScheduleRoomId;
  elements.adminRoomSelect.innerHTML = roomOptions.length
    ? roomOptions.join("")
    : '<option value="">No active rooms</option>';
  if (roomOptions.length) {
    elements.adminRoomSelect.value =
      activeRooms.some((room) => String(room.id) === previousRoomId)
        ? previousRoomId
        : activeRooms[0].id;
  }
  renderManualDurationOptions(currentState);
  if (elements.adminScheduleRoomFilter) {
    const scheduleRoomOptions = ['<option value="all">All rooms</option>'].concat(
      (currentState.rooms || []).map((room) => `<option value="${room.id}">${room.name}</option>`),
    );
    elements.adminScheduleRoomFilter.innerHTML = scheduleRoomOptions.join("");
    selectedAdminScheduleRoomId = (currentState.rooms || []).some((room) => String(room.id) === previousScheduleRoomId)
      ? previousScheduleRoomId
      : "all";
    elements.adminScheduleRoomFilter.value = selectedAdminScheduleRoomId;
  }
  if (elements.adminScheduleDate && elements.adminScheduleDate.value !== selectedAdminScheduleDate) {
    elements.adminScheduleDate.value = selectedAdminScheduleDate;
  }

  if (!isAdmin) {
    setActiveAdminTab("overview");
    adminSearchResults = null;
    elements.adminAnalyticsGrid && (elements.adminAnalyticsGrid.innerHTML = "");
    elements.adminRoomBreakdown && (elements.adminRoomBreakdown.innerHTML = "");
    elements.adminStaffBreakdown && (elements.adminStaffBreakdown.innerHTML = "");
    elements.adminActivityList && (elements.adminActivityList.innerHTML = "");
    elements.adminRoomStaffList && (elements.adminRoomStaffList.innerHTML = "");
    elements.adminStaffCatalogList && (elements.adminStaffCatalogList.innerHTML = "");
    elements.adminAccountsList && (elements.adminAccountsList.innerHTML = "");
    elements.adminAccountDetail && (elements.adminAccountDetail.innerHTML = "");
    elements.adminTestCaseSummary && (elements.adminTestCaseSummary.innerHTML = "");
    elements.adminTestCasesList && (elements.adminTestCasesList.innerHTML = "");
    elements.adminManualStaffOptions && (elements.adminManualStaffOptions.innerHTML = "");
    elements.adminDaySummary && (elements.adminDaySummary.innerHTML = "");
    elements.adminDaySchedule && (elements.adminDaySchedule.innerHTML = "");
    elements.adminBookingResults.innerHTML = "";
    selectedAdminAccountId = null;
    return;
  }

  setActiveAdminTab(activeAdminTab);
  renderAdminDaySummary(currentState);
  renderAdminDaySchedule(currentState);

  if (elements.adminAnalyticsGrid) {
    const analytics = currentState.adminAnalytics;
    const cards = analytics
      ? [
          { label: "Total bookings", value: analytics.total_bookings },
          { label: "Pending", value: analytics.pending_bookings },
          { label: "Paid", value: analytics.paid_bookings },
          { label: "Refunded", value: analytics.refunded_bookings },
          { label: "Active rooms", value: analytics.active_rooms },
          { label: "Staff profiles", value: analytics.total_staff_profiles },
          { label: "Active staff", value: analytics.active_staff_profiles },
          { label: "Staff add-ons booked", value: analytics.staff_assignment_count },
          {
            label: "Net revenue",
            value: formatMoney(analytics.net_revenue_cents, analytics.currency),
          },
        ]
      : [];

    elements.adminAnalyticsGrid.innerHTML = cards.length
      ? cards
          .map(
            (card) => `
              <article class="metric-card">
                <span class="metric-label">${card.label}</span>
                <strong class="metric-value">${card.value}</strong>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">Analytics will appear once booking data is available.</div>';
  }

  if (elements.adminRoomBreakdown) {
    const roomSummaries = currentState.adminAnalytics?.room_summaries || [];
    elements.adminRoomBreakdown.innerHTML = roomSummaries.length
      ? roomSummaries
          .map(
            (room) => `
              <article class="admin-room-card">
                <header>
                  <h4>${room.room_name}</h4>
                  <strong>${formatMoney(room.revenue_cents, currentState.adminAnalytics.currency)}</strong>
                </header>
                <p>${room.total_bookings} booking${room.total_bookings === 1 ? "" : "s"} recorded</p>
                <div class="room-meta">
                  <span class="pill">${room.paid_bookings} paid or refunded</span>
                  <span class="pill">${room.total_bookings - room.paid_bookings} unpaid or cancelled</span>
                </div>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No room activity yet.</div>';
  }

  if (elements.adminStaffBreakdown) {
    const staffSummaries = currentState.adminAnalytics?.staff_summaries || [];
    elements.adminStaffBreakdown.innerHTML = staffSummaries.length
      ? staffSummaries
          .map(
            (staff) => `
              <article class="admin-room-card">
                <header>
                  <h4>${staff.staff_name}</h4>
                  <strong>${formatMoney(staff.revenue_cents, currentState.adminAnalytics.currency)}</strong>
                </header>
                <p>${staff.total_bookings} booking${staff.total_bookings === 1 ? "" : "s"} with this staff profile</p>
                <div class="room-meta">
                  <span class="pill">${staff.assigned_rooms} assigned room${staff.assigned_rooms === 1 ? "" : "s"}</span>
                  <span class="pill ${staff.active ? "" : "muted"}">${staff.active ? "Active" : "Inactive"}</span>
                </div>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No staff utilization data yet.</div>';
  }

  if (elements.adminActivityList) {
    const activity = currentState.adminActivity || [];
    elements.adminActivityList.innerHTML = activity.length
      ? activity
          .map(
            (item) => `
              <article class="admin-activity-card">
                <header>
                  <strong>${formatActivityAction(item.action)}</strong>
                  <span>${formatBookingDate(item.created_at)}</span>
                </header>
                <p>${item.actor_email || "System"}${item.booking_id ? ` • Booking ${item.booking_id}` : ""}</p>
                <p>${item.details ? JSON.stringify(item.details) : "No extra details recorded."}</p>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No activity recorded yet.</div>';
  }

  if (elements.adminAccountsList && elements.adminAccountDetail) {
    const accounts = currentState.adminUsers || [];
    if (!accounts.length) {
      selectedAdminAccountId = null;
      elements.adminAccountsList.innerHTML = '<div class="empty-state">No accounts are available yet.</div>';
      elements.adminAccountDetail.innerHTML = '<div class="empty-state">Select an account once profiles exist.</div>';
    } else {
      if (!accounts.some((account) => String(account.id) === String(selectedAdminAccountId))) {
        selectedAdminAccountId = accounts[0].id;
      }
      const selectedAccount =
        accounts.find((account) => String(account.id) === String(selectedAdminAccountId)) || accounts[0];
      elements.adminAccountsList.innerHTML = accounts
        .map((account) => renderAdminAccountListItem(account, String(account.id) === String(selectedAccount.id)))
        .join("");
      elements.adminAccountDetail.innerHTML = renderAdminAccountDetail(selectedAccount, currentState.currentUser);
    }
  }

  if (elements.adminTestCasesList) {
    const testCases = [...(currentState.adminTestCases || [])].sort((left, right) => {
      const leftMeta = getTestCaseHealthMeta(left.health);
      const rightMeta = getTestCaseHealthMeta(right.health);
      if (leftMeta.sortOrder !== rightMeta.sortOrder) {
        return leftMeta.sortOrder - rightMeta.sortOrder;
      }
      return left.title.localeCompare(right.title);
    });
    renderAdminTestCaseSummary(testCases);
    elements.adminTestCasesList.innerHTML = testCases.length
      ? testCases.map(renderAdminTestCaseCard).join("")
      : '<div class="empty-state">No backend test cases are registered yet.</div>';
  }

  const bookingResults = adminSearchResults || currentState.adminBookings;
  elements.adminBookingResults.innerHTML = bookingResults.length
    ? bookingResults.map(renderAdminBookingCard).join("")
    : `
        <div class="empty-state">
          No admin booking results yet. Search by email, booking code, or status.
        </div>
      `;

  if (elements.adminStaffCatalogList) {
    const profiles = currentState.adminStaffProfiles || [];
    elements.adminStaffCatalogList.innerHTML = profiles.length
      ? profiles.map(renderStaffCatalogCard).join("")
      : '<div class="empty-state">Create your first staff profile to start assigning people to rooms.</div>';
  }

  if (elements.adminRoomStaffList) {
    const rooms = currentState.rooms || [];
    elements.adminRoomStaffList.innerHTML = rooms.length
      ? rooms.map((room) => renderRoomStaffAssignmentCard(room, currentState.adminStaffProfiles)).join("")
      : '<div class="empty-state">No rooms available for staff assignment.</div>';
  }

  renderManualBookingStaffOptions(currentState);
}
