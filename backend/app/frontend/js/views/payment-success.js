import { elements, toggleHidden } from "../dom.js?v=20260401r";

let reloadPaymentSuccessAction = null;
let paymentSuccessPollTimer = null;
let paymentSuccessPollCount = 0;

function stopPolling() {
  if (paymentSuccessPollTimer) {
    window.clearInterval(paymentSuccessPollTimer);
    paymentSuccessPollTimer = null;
  }
  paymentSuccessPollCount = 0;
}

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "full",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatCurrency(cents, currency) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "CAD",
  }).format((cents || 0) / 100);
}

function isAdminWaivedPayment(booking) {
  return booking.price_cents === 0 && String(booking.payment_intent_id || "").startsWith("admin_waived_");
}

function isAdminManualPayment(booking) {
  return String(booking.payment_intent_id || "").startsWith("admin_manual_paid_");
}

function renderPaymentSuccessSummary(booking) {
  if (!elements.paymentSuccessSummary) {
    return;
  }

  const settlementLine = isAdminWaivedPayment(booking)
    ? "Admin skipped Stripe and marked this booking free."
    : isAdminManualPayment(booking)
      ? "Admin marked this booking paid manually."
      : booking.confirmed_at
        ? `Payment confirmed ${formatBookingDate(booking.confirmed_at)}.`
        : "Payment confirmation is still being checked.";

  elements.paymentSuccessSummary.innerHTML = `
    <div class="summary-line"><span>Room</span><strong>${booking.room_name || "Studio booking"}</strong></div>
    <div class="summary-line"><span>Starts</span><strong>${formatBookingDate(booking.start_time)}</strong></div>
    <div class="summary-line"><span>Duration</span><strong>${booking.duration_minutes / 60} hour${booking.duration_minutes === 60 ? "" : "s"}</strong></div>
    <div class="summary-line"><span>Booked at</span><strong>${formatBookingDate(booking.created_at)}</strong></div>
    <div class="summary-line"><span>Settlement</span><strong>${settlementLine}</strong></div>
  `;
}

function getPaymentSuccessTitle(booking, paymentSettled, paymentStillProcessing) {
  if (isAdminWaivedPayment(booking)) {
    return "Booking confirmed without Stripe";
  }
  if (isAdminManualPayment(booking)) {
    return "Booking marked paid";
  }
  if (paymentSettled) {
    return "Payment successful";
  }
  if (paymentStillProcessing) {
    return "Payment submitted";
  }
  return `Payment status: ${booking.status}`;
}

function getPaymentSuccessCopy(booking, paymentSettled, paymentStillProcessing) {
  if (isAdminWaivedPayment(booking)) {
    return "Admin skipped checkout and confirmed the booking for free.";
  }
  if (isAdminManualPayment(booking)) {
    return "Admin marked this booking as paid so the rest of the flow can be tested.";
  }
  if (paymentSettled) {
    return "Your payment went through and the booking is confirmed.";
  }
  if (paymentStillProcessing) {
    return "Stripe accepted the payment step. This page is checking for final booking confirmation now.";
  }
  return "This booking changed after payment. Review the booking details below.";
}

function ensurePolling(booking) {
  if (!reloadPaymentSuccessAction || !booking || booking.status !== "PendingPayment") {
    stopPolling();
    return;
  }
  if (paymentSuccessPollTimer) {
    return;
  }

  paymentSuccessPollTimer = window.setInterval(async () => {
    paymentSuccessPollCount += 1;
    await reloadPaymentSuccessAction("Checking payment status...");
    if (paymentSuccessPollCount >= 10) {
      stopPolling();
    }
  }, 3000);
}

export function initPaymentSuccessView(actions) {
  reloadPaymentSuccessAction = actions?.reloadPaymentSuccess || null;
  elements.paymentSuccessActions?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-payment-success-action]");
    if (!button) {
      return;
    }
    if (button.dataset.paymentSuccessAction === "refresh-status" && reloadPaymentSuccessAction) {
      await reloadPaymentSuccessAction("Checking payment status...");
    }
  });
}

export function renderPaymentSuccessView(state) {
  if (!elements.paymentSuccessEmpty || !elements.paymentSuccessCard) {
    return;
  }

  const booking = state.selectedBooking;
  const hasBooking = Boolean(booking);
  toggleHidden(elements.paymentSuccessEmpty, hasBooking);
  toggleHidden(elements.paymentSuccessCard, !hasBooking);

  if (!booking) {
    stopPolling();
    return;
  }

  const paymentSettled = booking.status === "Paid" || booking.status === "Completed";
  const paymentStillProcessing = booking.status === "PendingPayment";
  const title = getPaymentSuccessTitle(booking, paymentSettled, paymentStillProcessing);
  const copy = getPaymentSuccessCopy(booking, paymentSettled, paymentStillProcessing);

  elements.paymentSuccessTitle.textContent = title;
  elements.paymentSuccessCopy.textContent = copy;
  elements.paymentSuccessMeta.innerHTML = `
    <span class="pill">${booking.booking_code}</span>
    <span class="pill">${formatCurrency(booking.price_cents, booking.currency)}</span>
    <span class="pill">${booking.status}</span>
    <span class="pill">${formatBookingDate(booking.start_time)}</span>
  `;
  renderPaymentSuccessSummary(booking);
  elements.paymentSuccessActions.innerHTML = `
    <a class="primary-button ghost-link" href="/booking?id=${booking.id}">View booking</a>
    <a class="ghost-button ghost-link" href="/bookings">Back to bookings</a>
    ${paymentStillProcessing ? '<button class="ghost-button" type="button" data-payment-success-action="refresh-status">Refresh status</button>' : ""}
  `;

  ensurePolling(booking);
  if (!paymentStillProcessing) {
    stopPolling();
  }
}
