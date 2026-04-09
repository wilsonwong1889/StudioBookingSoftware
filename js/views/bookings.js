import { api } from "../api.js?v=20260401r";
import { getSearchParam } from "../config.js?v=20260401r";
import { elements } from "../dom.js?v=20260401r";
import { setState, state } from "../state.js?v=20260401r";

const MIN_DURATION_MINUTES = 60;
const MAX_DURATION_MINUTES = 300;
let selectedStaffIds = new Set();

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
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

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format((cents || 0) / 100);
}

function formatStatusLabel(status) {
  return String(status || "Unknown")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
}

function getStatusClassName(status) {
  return `status-${String(status || "unknown").toLowerCase()}`;
}

function getBookingSortValue(value) {
  return value ? new Date(value).getTime() : 0;
}

const RECENT_BOOKING_SECTIONS = [
  {
    key: "Completed",
    label: "Completed / checked in",
    description: "Newest checked-in sessions first.",
  },
  {
    key: "Paid",
    label: "Paid",
    description: "Paid bookings waiting for their session stay next.",
  },
  {
    key: "Refunded",
    label: "Refunded",
    description: "Refunded bookings stay above cancellations.",
  },
  {
    key: "Cancelled",
    label: "Cancelled",
    description: "Cancelled bookings stay at the bottom.",
  },
];

function formatCountdown(seconds) {
  const safeSeconds = Math.max(0, seconds || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatBookingCount(count) {
  return `${count} booking${count === 1 ? "" : "s"}`;
}

function getRecentBookingSectionKey(booking) {
  if (booking.status === "Completed") {
    return "Completed";
  }
  if (booking.status === "Paid") {
    return "Paid";
  }
  if (booking.status === "Refunded") {
    return "Refunded";
  }
  if (booking.status === "Cancelled") {
    return "Cancelled";
  }
  return "Cancelled";
}

function getRecentBookingTimeValue(booking) {
  if (booking.status === "Completed") {
    return getBookingSortValue(booking.checked_in_at || booking.start_time || booking.created_at);
  }
  if (booking.status === "Paid") {
    return getBookingSortValue(booking.confirmed_at || booking.created_at || booking.start_time);
  }
  if (booking.status === "Refunded") {
    return getBookingSortValue(booking.updated_at || booking.created_at || booking.start_time);
  }
  if (booking.status === "Cancelled") {
    return getBookingSortValue(booking.cancelled_at || booking.created_at || booking.start_time);
  }
  return getBookingSortValue(booking.start_time || booking.created_at);
}

function renderRecentBookingSections(bookings) {
  const sections = RECENT_BOOKING_SECTIONS.map((section) => {
    const groupedBookings = bookings
      .filter((booking) => getRecentBookingSectionKey(booking) === section.key)
      .sort((left, right) => getRecentBookingTimeValue(right) - getRecentBookingTimeValue(left));

    return {
      ...section,
      bookings: groupedBookings,
    };
  }).filter((section) => section.bookings.length);

  if (!sections.length) {
    return `
      <div class="empty-state">
        No recent bookings yet.
      </div>
    `;
  }

  return sections
    .map(
      (section) => `
        <section class="booking-history-group">
          <div class="booking-history-group-header">
            <div class="booking-history-group-copy">
              <p class="panel-kicker">${section.label}</p>
              <p>${section.description}</p>
            </div>
            <span class="pill">${formatBookingCount(section.bookings.length)}</span>
          </div>
          <div class="booking-list">
            ${section.bookings.map((booking) => renderBookingCard(booking)).join("")}
          </div>
        </section>
      `,
    )
    .join("");
}

function buildDurationValues(limitMinutes = MAX_DURATION_MINUTES) {
  const safeLimit = Math.max(MIN_DURATION_MINUTES, Math.min(limitMinutes, MAX_DURATION_MINUTES));
  const values = [];
  for (let duration = MIN_DURATION_MINUTES; duration <= safeLimit; duration += MIN_DURATION_MINUTES) {
    values.push(duration);
  }
  return values;
}

function renderStaffImage(photoUrl, label) {
  if (photoUrl) {
    return `<img class="staff-avatar" src="${photoUrl}" alt="${label}" loading="lazy" />`;
  }
  return `<div class="staff-avatar staff-avatar-fallback">${label.slice(0, 1).toUpperCase()}</div>`;
}

function renderTagGroup(label, values = []) {
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

function getSelectedDuration() {
  return Number(elements.bookingDurationSelect?.value || MIN_DURATION_MINUTES);
}

function getSelectedRoom() {
  return state.rooms.find((room) => String(room.id) === elements.bookingRoomSelect?.value);
}

function getSelectedStaffOptions(room) {
  const roles = room?.staff_roles || [];
  return roles.filter((role) => selectedStaffIds.has(role.id));
}

function calculateEstimatedTotal(room, durationMinutes) {
  const baseRate = (room?.hourly_rate_cents || 0) * (durationMinutes / 60);
  const staffTotal = getSelectedStaffOptions(room).reduce(
    (total, role) => total + (role.add_on_price_cents || 0),
    0,
  );
  return baseRate + staffTotal;
}

function renderSelectedStaffBreakdown(room) {
  const selectedStaff = getSelectedStaffOptions(room);
  if (!selectedStaff.length) {
    return '<div class="summary-line"><span>Staff add-ons</span><strong>None selected</strong></div>';
  }

  return selectedStaff
    .map(
      (role) => `
        <div class="summary-line">
          <span>${role.name}</span>
          <strong>${formatCurrency(role.add_on_price_cents)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderStaffOptions(currentState) {
  if (!elements.bookingStaffSection || !elements.bookingStaffOptions) {
    return;
  }

  const emptyState = elements.bookingStaffSection.querySelector("[data-booking-staff-empty]");
  const countPill = elements.bookingStaffSection.querySelector("[data-booking-staff-count]");
  const room = currentState.rooms.find((item) => String(item.id) === elements.bookingRoomSelect?.value);
  if (!room) {
    selectedStaffIds = new Set();
    elements.bookingStaffOptions.innerHTML = "";
    elements.bookingStaffOptions.classList.add("hidden");
    if (emptyState) {
      emptyState.classList.remove("hidden");
      emptyState.textContent = "Choose a room to preview available staff for this session.";
    }
    if (countPill) {
      countPill.classList.add("hidden");
      countPill.textContent = "";
    }
    return;
  }

  const staffRoles = room.staff_roles || [];
  if (!staffRoles.length) {
    selectedStaffIds = new Set();
    elements.bookingStaffOptions.innerHTML = "";
    elements.bookingStaffOptions.classList.add("hidden");
    if (emptyState) {
      emptyState.classList.remove("hidden");
      emptyState.textContent = `No staff profiles are assigned to ${room.name} yet.`;
    }
    if (countPill) {
      countPill.classList.add("hidden");
      countPill.textContent = "";
    }
    return;
  }

  const availableIds = new Set(staffRoles.map((role) => role.id));
  selectedStaffIds = new Set([...selectedStaffIds].filter((roleId) => availableIds.has(roleId)));

  if (emptyState) {
    emptyState.classList.add("hidden");
  }
  elements.bookingStaffOptions.classList.remove("hidden");
  if (countPill) {
    const selectedCount = staffRoles.filter((role) => selectedStaffIds.has(role.id)).length;
    countPill.classList.remove("hidden");
    countPill.textContent = selectedCount
      ? `${selectedCount} selected of ${staffRoles.length}`
      : `${staffRoles.length} available`;
  }
  elements.bookingStaffOptions.innerHTML = staffRoles
    .map(
      (role) => `
        <label class="staff-option-card">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${role.id}" ${selectedStaffIds.has(role.id) ? "checked" : ""} />
          </div>
          ${renderStaffImage(role.photo_url, role.name)}
          <div class="staff-option-copy">
            <strong>${role.name}</strong>
            <span>${role.description || "Optional staff support for this booking."}</span>
            ${renderTagGroup("Skills", role.skills || [])}
            ${renderTagGroup("Talents", role.talents || [])}
          </div>
          <strong class="staff-option-price">${formatCurrency(role.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function renderDurationOptions() {
  if (!elements.bookingStartSelect || !elements.bookingDurationSelect) {
    return;
  }
  const selectedStart = elements.bookingStartSelect.value;
  const maxDuration = state.availability?.max_duration_minutes_by_start?.[selectedStart];
  const previousValue = Number(elements.bookingDurationSelect.value || MIN_DURATION_MINUTES);

  const allowedDurations = buildDurationValues(maxDuration || MAX_DURATION_MINUTES);
  elements.bookingDurationSelect.innerHTML = allowedDurations
    .map((duration) => `<option value="${duration}">${formatDuration(duration)}</option>`)
    .join("");
  elements.bookingDurationSelect.value = allowedDurations.includes(previousValue)
    ? String(previousValue)
    : String(MIN_DURATION_MINUTES);
}

function renderAvailabilitySummary() {
  if (!elements.availabilitySummary) {
    return;
  }
  const availability = state.availability;
  if (!availability) {
    elements.availabilitySummary.classList.add("hidden");
    elements.availabilitySummary.textContent = "";
    return;
  }

  const count = availability.available_start_times.length;
  const roomName = state.rooms.find((room) => String(room.id) === elements.bookingRoomSelect.value)?.name || "selected room";
  elements.availabilitySummary.classList.remove("hidden");
  elements.availabilitySummary.innerHTML =
    count > 0
      ? `
        <strong>${count} available start times</strong>
        <span>${roomName} on ${availability.date} in ${availability.timezone}.</span>
      `
      : `
        <strong>No openings found</strong>
        <span>${roomName} has no bookable start times on ${availability.date}.</span>
      `;
}

function applyRequestedRoomSelection(currentState) {
  const requestedRoomId = getSearchParam("room") || getSearchParam("id");
  if (!requestedRoomId || !elements.bookingRoomSelect) {
    return;
  }

  const requestedRoomExists = currentState.rooms.some(
    (room) => String(room.id) === requestedRoomId && room.active,
  );
  if (requestedRoomExists) {
    elements.bookingRoomSelect.value = requestedRoomId;
  }
}

function renderStartTimeOptions(currentState) {
  if (!elements.bookingStartSelect || !elements.bookingDurationSelect) {
    return;
  }
  const availability = currentState.availability;
  if (!availability) {
    elements.bookingStartSelect.innerHTML = "";
    renderDurationOptions();
    return;
  }

  const existingValue = elements.bookingStartSelect.value;
  const options = availability.available_start_times.map((startTime) => {
    const label = formatBookingDate(startTime);
    return `<option value="${startTime}">${label}</option>`;
  });

  elements.bookingStartSelect.innerHTML = options.join("");
  if (availability.available_start_times.includes(existingValue)) {
    elements.bookingStartSelect.value = existingValue;
  } else {
    elements.bookingStartSelect.value = availability.available_start_times[0] || "";
  }
  renderDurationOptions();
}

function renderSlotList(currentState) {
  if (!elements.bookingSlotList) {
    return;
  }

  const availability = currentState.availability;
  if (!availability?.available_start_times?.length) {
    elements.bookingSlotList.classList.add("hidden");
    elements.bookingSlotList.innerHTML = "";
    return;
  }

  const selectedStart = elements.bookingStartSelect.value;
  elements.bookingSlotList.classList.remove("hidden");
  elements.bookingSlotList.innerHTML = availability.available_start_times
    .map((startTime) => {
      const isActive = startTime === selectedStart;
      const maxDuration = availability.max_duration_minutes_by_start[startTime];
      return `
        <button
          class="slot-card ${isActive ? "is-selected" : ""}"
          type="button"
          data-slot-start="${startTime}"
        >
          <strong>${formatTimeOnly(startTime)}</strong>
          <span>Up to ${formatDuration(Math.min(maxDuration, MAX_DURATION_MINUTES))}</span>
        </button>
      `;
    })
    .join("");
}

function renderBookingSummary(currentState) {
  if (!elements.bookingSummaryCard || !elements.bookingSummaryTitle || !elements.bookingSummaryMeta) {
    return;
  }

  const selectedRoom = currentState.rooms.find((room) => String(room.id) === elements.bookingRoomSelect.value);
  const selectedStart = elements.bookingStartSelect?.value;
  const selectedDuration = getSelectedDuration();

  if (!selectedRoom) {
    elements.bookingSummaryTitle.textContent = "Pick a room and date";
    elements.bookingSummaryMeta.innerHTML = `
      <div class="empty-state">Choose a room and load availability to see your selection details here.</div>
    `;
    return;
  }

  if (!selectedStart) {
    elements.bookingSummaryTitle.textContent = selectedRoom.name;
    elements.bookingSummaryMeta.innerHTML = `
      <div class="summary-stack">
        <div class="summary-line"><span>Rate</span><strong>${new Intl.NumberFormat("en-US", { style: "currency", currency: "CAD" }).format((selectedRoom.hourly_rate_cents || 0) / 100)}/hour CAD</strong></div>
        <div class="summary-line"><span>Date</span><strong>${elements.bookingDateInput.value || "Select a date"}</strong></div>
        ${renderSelectedStaffBreakdown(selectedRoom)}
        <div class="empty-state">Load availability and pick a start time to continue.</div>
      </div>
    `;
    return;
  }

  const estimatedPrice = calculateEstimatedTotal(selectedRoom, selectedDuration);
  elements.bookingSummaryTitle.textContent = `${selectedRoom.name} at ${formatTimeOnly(selectedStart)}`;
  elements.bookingSummaryMeta.innerHTML = `
    <div class="summary-stack">
      <div class="summary-line"><span>Date</span><strong>${formatBookingDate(selectedStart)}</strong></div>
      <div class="summary-line"><span>Duration</span><strong>${formatDuration(selectedDuration)}</strong></div>
      ${renderSelectedStaffBreakdown(selectedRoom)}
      <div class="summary-line"><span>Estimated total</span><strong>${formatCurrency(estimatedPrice)} CAD</strong></div>
      <div class="summary-line"><span>Booking access</span><strong>${currentState.currentUser ? "Ready to submit" : "Log in required"}</strong></div>
    </div>
  `;
}

function renderBookingCard(booking, { highlight = false } = {}) {
  const isPending = booking.status === "PendingPayment";
  const actionLabel = isPending ? "Finish payment" : "View details";
  const countdownLine =
    isPending && booking.payment_expires_at
      ? `
        <div class="summary-line">
          <span>Payment window</span>
          <strong>
            Saved until ${formatBookingDate(booking.payment_expires_at)}${
              typeof booking.payment_seconds_remaining === "number"
                ? ` • ${formatCountdown(booking.payment_seconds_remaining)} left`
                : ""
            }
          </strong>
        </div>
      `
      : "";

  return `
    <article class="booking-card ${highlight ? "booking-card-pending" : "booking-card-secondary"}">
      <div class="booking-card-top">
        <div class="booking-card-copy">
          <div class="room-meta">
            <span class="pill ${getStatusClassName(booking.status)}">${formatStatusLabel(booking.status)}</span>
            <span class="pill">${booking.booking_code}</span>
          </div>
          <h4>${booking.room_name || "Studio booking"}</h4>
          <p>${formatBookingDate(booking.start_time)} to ${formatBookingDate(booking.end_time)}</p>
        </div>
        <strong class="booking-card-price">${formatCurrency(booking.price_cents)}</strong>
      </div>
      <div class="summary-stack booking-card-summary">
        <div class="summary-line"><span>Duration</span><strong>${formatDuration(booking.duration_minutes)}</strong></div>
        ${countdownLine}
        ${booking.note ? `<div class="summary-line"><span>Notes</span><strong>${booking.note}</strong></div>` : ""}
      </div>
      <div class="room-actions">
        <a class="${isPending ? "primary-button primary-link" : "ghost-button ghost-link"}" href="/booking?id=${booking.id}">${actionLabel}</a>
        ${
          booking.status === "PendingPayment" || booking.status === "Paid"
            ? `<button class="ghost-button" type="button" data-booking-action="cancel" data-booking-id="${booking.id}">Cancel</button>`
            : ""
        }
      </div>
    </article>
  `;
}

export function initBookingsView(actions) {
  if (
    !elements.bookingEmpty ||
    !elements.availabilityForm ||
    !elements.bookingForm ||
    !elements.bookingHistoryPanel ||
    !elements.pendingBookingsList ||
    !elements.recentBookingsList
  ) {
    return;
  }

  elements.bookingDateInput.value = todayString();

  elements.bookingRoomSelect?.addEventListener("change", () => {
    selectedStaffIds = new Set();
    setState({ availability: null });
    if (elements.bookingStartSelect) {
      elements.bookingStartSelect.innerHTML = "";
    }
    if (elements.bookingDurationSelect) {
      elements.bookingDurationSelect.innerHTML = "";
    }
    if (elements.bookingSlotList) {
      elements.bookingSlotList.innerHTML = "";
      elements.bookingSlotList.classList.add("hidden");
    }
    renderStaffOptions(state);
    renderBookingSummary(state);
  });

  elements.availabilityForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const roomId = elements.bookingRoomSelect.value;
    const date = elements.bookingDateInput.value;

    if (!roomId || !date) {
      setState({ message: "Choose a room and date first." });
      return;
    }

    try {
      setState({ message: "Loading availability..." });
      const availability = await api.getAvailability(roomId, date);
      setState({ availability, message: "Availability loaded." });
    } catch (error) {
      elements.bookingStartSelect.innerHTML = "";
      elements.bookingDurationSelect.innerHTML = "";
      selectedStaffIds = new Set();
      renderStaffOptions(state);
      if (elements.bookingSlotList) {
        elements.bookingSlotList.innerHTML = "";
      }
      setState({ availability: null, message: error.message });
    }
  });

  elements.bookingStartSelect.addEventListener("change", () => {
    renderDurationOptions();
    renderSlotList(state);
    renderBookingSummary(state);
  });

  elements.bookingDurationSelect.addEventListener("change", () => {
    renderBookingSummary(state);
  });

  elements.bookingStaffOptions?.addEventListener("change", (event) => {
    const input = event.target.closest("input[type='checkbox']");
    if (!input) {
      return;
    }

    if (input.checked) {
      selectedStaffIds.add(input.value);
    } else {
      selectedStaffIds.delete(input.value);
    }
    renderBookingSummary(state);
  });

  if (elements.bookingSlotList) {
    elements.bookingSlotList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-slot-start]");
      if (!button) {
        return;
      }
      elements.bookingStartSelect.value = button.dataset.slotStart;
      renderDurationOptions();
      renderSlotList(state);
      renderBookingSummary(state);
    });
  }

  elements.bookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentUser) {
      setState({ message: "Log in to complete a booking." });
      return;
    }

    const roomId = elements.bookingRoomSelect.value;
    const startTime = elements.bookingStartSelect.value;
    const duration = Number(elements.bookingDurationSelect.value);

    if (!roomId || !startTime || !duration) {
      setState({ message: "Load availability and choose a valid slot first." });
      return;
    }

    try {
      setState({ message: "Creating booking..." });
      const booking = await api.createBooking({
        room_id: roomId,
        start_time: startTime,
        duration_minutes: duration,
        note: elements.bookingNoteInput?.value?.trim() || null,
        staff_assignments: [...selectedStaffIds],
      });
      if (elements.bookingNoteInput) {
        elements.bookingNoteInput.value = "";
      }
      selectedStaffIds = new Set();
      window.location.href = `/booking?id=${booking.id}`;
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.bookingHistoryPanel.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-booking-action='cancel']");
    if (!button) {
      return;
    }

    try {
      setState({ message: "Cancelling booking..." });
      await api.cancelBooking(button.dataset.bookingId, { reason: "Cancelled by user" });
      await actions.refreshAvailabilityAndBookings("Booking cancelled.");
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

export function renderBookingsView(currentState) {
  if (
    !elements.bookingEmpty ||
    !elements.availabilityForm ||
    !elements.bookingForm ||
    !elements.pendingBookingsList ||
    !elements.recentBookingsList ||
    !elements.recentBookingsShell
  ) {
    return;
  }

  const isSignedIn = Boolean(currentState.currentUser);
  elements.bookingEmpty.classList.toggle("hidden", isSignedIn);
  elements.availabilityForm.classList.remove("hidden");
  elements.bookingForm.classList.remove("hidden");
  elements.availabilitySummary.classList.toggle("hidden", !currentState.availability);

  const existingRoomId = elements.bookingRoomSelect.value;
  const roomOptions = currentState.rooms
    .filter((room) => room.active)
    .map((room) => `<option value="${room.id}">${room.name}</option>`);
  elements.bookingRoomSelect.innerHTML = roomOptions.length
    ? roomOptions.join("")
    : '<option value="">No active rooms available</option>';
  if (roomOptions.length && currentState.rooms.some((room) => room.id === existingRoomId && room.active)) {
    elements.bookingRoomSelect.value = existingRoomId;
  }
  applyRequestedRoomSelection(currentState);

  if (!elements.bookingDateInput.value) {
    elements.bookingDateInput.value = todayString();
  }

  renderStartTimeOptions(currentState);
  renderAvailabilitySummary();
  renderSlotList(currentState);
  renderStaffOptions(currentState);
  renderBookingSummary(currentState);

  const bookingSubmitButton = elements.bookingForm.querySelector("button[type='submit']");
  if (bookingSubmitButton) {
    bookingSubmitButton.disabled = !isSignedIn;
    bookingSubmitButton.textContent = isSignedIn ? "Save 5-minute spot hold" : "Log in to book";
  }

  const pendingBookings = currentState.bookings
    .filter((booking) => booking.status === "PendingPayment")
    .sort((left, right) => {
      return (
        getBookingSortValue(left.payment_expires_at || left.start_time) -
        getBookingSortValue(right.payment_expires_at || right.start_time)
      );
    });
  const recentBookings = currentState.bookings
    .filter((booking) => booking.status !== "PendingPayment")
    .sort((left, right) => getRecentBookingTimeValue(right) - getRecentBookingTimeValue(left));

  if (elements.pendingBookingsCount) {
    elements.pendingBookingsCount.classList.toggle("hidden", !isSignedIn);
    elements.pendingBookingsCount.textContent = `${pendingBookings.length} pending`;
  }

  if (elements.recentBookingsCount) {
    elements.recentBookingsCount.textContent = formatBookingCount(recentBookings.length);
  }

  if (!isSignedIn) {
    elements.pendingBookingsList.innerHTML = `
      <div class="empty-state">
        Log in to view your booking history and complete a booking after checking availability.
      </div>
    `;
    elements.recentBookingsShell.classList.add("hidden");
    elements.recentBookingsList.innerHTML = "";
  } else if (!currentState.bookings.length) {
    elements.pendingBookingsList.innerHTML = `
      <div class="empty-state">
        No pending bookings right now. Create a new booking from the availability flow above.
      </div>
    `;
    elements.recentBookingsShell.classList.remove("hidden");
    elements.recentBookingsShell.open = false;
    elements.recentBookingsList.innerHTML = `
      <div class="empty-state">
        No recent bookings yet.
      </div>
    `;
  } else {
    elements.pendingBookingsList.innerHTML = pendingBookings.length
      ? pendingBookings.map((booking) => renderBookingCard(booking, { highlight: true })).join("")
      : `
        <div class="empty-state">
          No pending bookings right now. Finished and older bookings are kept in the recent bookings dropdown below.
        </div>
      `;

    elements.recentBookingsShell.classList.remove("hidden");
    if (!recentBookings.length) {
      elements.recentBookingsShell.open = false;
    }
    elements.recentBookingsList.innerHTML = renderRecentBookingSections(recentBookings);
  }
}
