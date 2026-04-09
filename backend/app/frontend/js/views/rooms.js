import { api } from "../api.js?v=20260408e";
import { elements } from "../dom.js?v=20260401r";
import { setState, state } from "../state.js?v=20260401r";

let editingRoomId = null;
let selectedCreateStaffIds = new Set();

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CAD",
  }).format((cents || 0) / 100);
}

function formatPreviewTimes(availableStartTimes) {
  return availableStartTimes.slice(0, 4).map((startTime) =>
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(startTime)),
  );
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function getPrimaryPhoto(room) {
  return Array.isArray(room.photos) && room.photos.length ? room.photos[0] : null;
}

function getRoomPhotoUrlInput() {
  return elements.roomForm?.querySelector("#room-photo-url");
}

function getRoomPhotoFileInput() {
  return elements.roomForm?.querySelector("#room-photo-file");
}

function getRoomPhotoPreview() {
  return elements.roomForm?.querySelector("#room-photo-preview");
}

function setRoomPhotoPreview(photoUrl, roomName = "Room") {
  const preview = getRoomPhotoPreview();
  if (!preview) {
    return;
  }

  if (!photoUrl) {
    preview.classList.add("empty-state");
    preview.innerHTML = "Upload a JPG photo to show this room across booking and room detail pages.";
    return;
  }

  preview.classList.remove("empty-state");
  preview.innerHTML = `
    <div class="staff-photo-preview-card">
      <img class="staff-photo-preview-image" src="${photoUrl}" alt="${roomName}" loading="lazy" />
      <div class="staff-option-copy">
        <strong>${roomName}</strong>
        <span>This image will appear as the primary room photo.</span>
      </div>
    </div>
  `;
}

function resetRoomForm() {
  editingRoomId = null;
  selectedCreateStaffIds = new Set();
  elements.roomForm?.reset();
  if (elements.roomFormId) {
    elements.roomFormId.value = "";
  }
  if (elements.roomFormTitle) {
    elements.roomFormTitle.textContent = "Create room";
  }
  if (elements.roomFormSubmit) {
    elements.roomFormSubmit.textContent = "Create room";
  }
  elements.roomFormCancel?.classList.add("hidden");
  if (elements.roomForm?.elements?.hourly_rate_cents) {
    elements.roomForm.elements.hourly_rate_cents.value = "5000";
  }
  if (elements.roomForm?.elements?.max_booking_duration_minutes) {
    elements.roomForm.elements.max_booking_duration_minutes.value = "300";
  }
  const roomPhotoUrlInput = getRoomPhotoUrlInput();
  if (roomPhotoUrlInput) {
    roomPhotoUrlInput.value = "";
  }
  setRoomPhotoPreview(null);
}

function populateRoomForm(room) {
  if (!elements.roomForm) {
    return;
  }

  editingRoomId = String(room.id);
  selectedCreateStaffIds = new Set((room.staff_roles || []).map((role) => String(role.id)));
  if (elements.roomFormId) {
    elements.roomFormId.value = editingRoomId;
  }
  elements.roomForm.elements.name.value = room.name || "";
  elements.roomForm.elements.description.value = room.description || "";
  elements.roomForm.elements.capacity.value = room.capacity || "";
  const roomPhotos = Array.isArray(room.photos) ? room.photos : [];
  const primaryPhoto = roomPhotos[0] || "";
  elements.roomForm.elements.photos.value = roomPhotos.slice(1).join("\n");
  elements.roomForm.elements.hourly_rate_cents.value = room.hourly_rate_cents || 5000;
  elements.roomForm.elements.max_booking_duration_minutes.value = room.max_booking_duration_minutes || 300;
  const roomPhotoUrlInput = getRoomPhotoUrlInput();
  if (roomPhotoUrlInput) {
    roomPhotoUrlInput.value = primaryPhoto;
  }
  setRoomPhotoPreview(primaryPhoto || null, room.name || "Room");
  if (elements.roomFormTitle) {
    elements.roomFormTitle.textContent = `Edit ${room.name}`;
  }
  if (elements.roomFormSubmit) {
    elements.roomFormSubmit.textContent = "Save room changes";
  }
  elements.roomFormCancel?.classList.remove("hidden");
}

function renderCreateRoomStaffOptions(currentState) {
  if (!elements.adminRoomCreateStaffSection || !elements.adminRoomCreateStaffOptions) {
    return;
  }

  const profiles = (currentState.adminStaffProfiles || []).filter(
    (profile) => profile.active || selectedCreateStaffIds.has(String(profile.id)),
  );
  if (!profiles.length) {
    selectedCreateStaffIds = new Set();
    elements.adminRoomCreateStaffOptions.innerHTML =
      '<div class="empty-state">Create staff profiles first, then select them here while creating a room.</div>';
    return;
  }

  elements.adminRoomCreateStaffOptions.innerHTML = profiles
    .map(
      (profile) => `
        <label class="staff-option-card staff-option-card-compact">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${profile.id}" ${selectedCreateStaffIds.has(String(profile.id)) ? "checked" : ""} />
          </div>
          <div class="staff-option-copy">
            <strong>${profile.name}</strong>
            <span>${profile.description || "Optional staff support for this room."}</span>
          </div>
          <strong class="staff-option-price">${formatCurrency(profile.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function collectCreateRoomStaffPayload() {
  const profilesById = new Map(
    (state.adminStaffProfiles || []).map((profile) => [String(profile.id), profile]),
  );

  return Array.from(selectedCreateStaffIds).flatMap((staffProfileId) => {
    const profile = profilesById.get(staffProfileId);
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

function renderAvailabilityPreview(roomId) {
  const supportsRoomPreview = Boolean(elements.roomsPreviewDate && elements.roomsPreviewButton);
  if (!supportsRoomPreview) {
    return "";
  }

  const preview = state.roomAvailabilityPreview?.[roomId];
  if (!preview) {
    return `
      <div class="availability-preview">
        <span class="availability-label">Availability preview</span>
        <p>Choose a date and click "Show availability" to preview open start times.</p>
      </div>
    `;
  }

  if (!preview.available_start_times.length) {
    return `
      <div class="availability-preview">
        <span class="availability-label">Availability preview</span>
        <p>No available start times for ${preview.date}.</p>
      </div>
    `;
  }

  const previewTimes = formatPreviewTimes(preview.available_start_times)
    .map((label) => `<span class="pill">${label}</span>`)
    .join("");
  return `
    <div class="availability-preview">
      <span class="availability-label">${preview.available_start_times.length} starts open on ${preview.date}</span>
      <div class="preview-pill-row">${previewTimes}</div>
    </div>
  `;
}

function renderRoomCard(room, canManageRooms) {
  const photoCount = Array.isArray(room.photos) ? room.photos.length : 0;
  const primaryPhoto = getPrimaryPhoto(room);
  const activeLabel = room.active ? "Active" : "Inactive";
  const staffCount = (room.staff_roles || []).length;
  const canEditRoom = canManageRooms && Boolean(elements.roomForm);
  const managementActions = canManageRooms
    ? [
        canEditRoom
          ? `<button class="ghost-button room-action" type="button" data-room-action="edit" data-room-id="${room.id}">Edit</button>`
          : "",
        room.active
          ? `<button class="ghost-button room-action" type="button" data-room-action="archive" data-room-id="${room.id}">Archive</button>`
          : `<button class="ghost-button room-action" type="button" data-room-action="restore" data-room-id="${room.id}">Restore</button>`,
        `<button class="ghost-button room-action room-action-danger" type="button" data-room-action="delete" data-room-id="${room.id}" data-room-name="${room.name}">Delete room</button>`,
      ].filter(Boolean).join("")
    : "";

  return `
    <article class="room-card room-card-rich">
      <div class="room-card-media">
        ${
          primaryPhoto
            ? `<img class="room-card-image" src="${primaryPhoto}" alt="${room.name}" loading="lazy" />`
            : '<div class="room-card-placeholder">No room image yet.</div>'
        }
      </div>
      <div class="room-card-top">
        <div>
          <h3>${room.name}</h3>
          <p>${room.description || "No description yet."}</p>
        </div>
        <span class="pill ${room.active ? "" : "muted"}">${activeLabel}</span>
      </div>
      <div class="room-meta">
        <span class="pill">${formatCurrency(room.hourly_rate_cents)}/hour CAD</span>
        <span class="pill">Max ${formatDuration(room.max_booking_duration_minutes || 300)}</span>
        <span class="pill">Capacity ${room.capacity || "n/a"}</span>
        <span class="pill">${photoCount} image${photoCount === 1 ? "" : "s"}</span>
        <span class="pill">${staffCount} staff option${staffCount === 1 ? "" : "s"}</span>
      </div>
      ${renderAvailabilityPreview(room.id)}
      <div class="room-actions">
        <a class="ghost-button ghost-link" href="/room?id=${room.id}">View details</a>
        <a class="primary-button" href="/bookings?room=${room.id}">Book this room</a>
        ${managementActions}
      </div>
    </article>
  `;
}

async function previewRoomsAvailability() {
  if (!elements.roomsPreviewDate || !state.rooms.length) {
    return;
  }

  const previewDate = elements.roomsPreviewDate.value;
  if (!previewDate) {
    setState({ message: "Choose a date to preview room availability." });
    return;
  }

  try {
    setState({ message: "Loading room availability..." });
    const previews = await Promise.all(
      state.rooms
        .filter((room) => room.active)
        .map(async (room) => [room.id, await api.getAvailability(room.id, previewDate)]),
    );
    setState({
      roomPreviewDate: previewDate,
      roomAvailabilityPreview: Object.fromEntries(previews),
      message: "Room availability loaded.",
    });
  } catch (error) {
    setState({ message: error.message });
  }
}

export function initRoomsView(actions) {
  if (elements.showInactiveToggle) {
    elements.showInactiveToggle.addEventListener("change", async (event) => {
      setState({
        showInactiveRooms: event.target.checked,
        roomAvailabilityPreview: {},
        message: "Room filter updated.",
      });
      await actions.refreshRooms();
    });
  }

  if (elements.roomsPreviewDate) {
    elements.roomsPreviewDate.value = state.roomPreviewDate;
  }

  if (elements.roomsPreviewButton) {
    elements.roomsPreviewButton.addEventListener("click", async () => {
      await previewRoomsAvailability();
    });
  }

  if (elements.roomForm) {
    elements.roomFormCancel?.addEventListener("click", () => {
      resetRoomForm();
      renderCreateRoomStaffOptions(state);
    });

    getRoomPhotoFileInput()?.addEventListener("change", () => {
      const file = getRoomPhotoFileInput()?.files?.[0];
      if (!file) {
        setRoomPhotoPreview(
          getRoomPhotoUrlInput()?.value || null,
          elements.roomForm?.elements?.name?.value || "Room",
        );
        return;
      }
      setRoomPhotoPreview(
        URL.createObjectURL(file),
        elements.roomForm?.elements?.name?.value || file.name,
      );
    });

    elements.adminRoomCreateStaffOptions?.addEventListener("change", (event) => {
      const input = event.target.closest("input[type='checkbox']");
      if (!input) {
        return;
      }

      if (input.checked) {
        selectedCreateStaffIds.add(input.value);
      } else {
        selectedCreateStaffIds.delete(input.value);
      }
    });

    elements.roomForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.roomForm);
      let primaryPhotoUrl = String(form.get("primary_photo_url") || "").trim() || null;
      const roomPhotoFile = getRoomPhotoFileInput()?.files?.[0];
      const additionalPhotos = String(form.get("photos") || "")
        .split("\n")
        .map((value) => value.trim())
        .filter(Boolean);
      if (roomPhotoFile) {
        const upload = await api.adminUploadRoomPhoto(roomPhotoFile);
        primaryPhotoUrl = upload.photo_url;
        const roomPhotoUrlInput = getRoomPhotoUrlInput();
        if (roomPhotoUrlInput) {
          roomPhotoUrlInput.value = primaryPhotoUrl;
        }
      }
      const photos = Array.from(new Set([primaryPhotoUrl, ...additionalPhotos].filter(Boolean)));

      const payload = {
        name: form.get("name"),
        description: form.get("description") || null,
        capacity: form.get("capacity") ? Number(form.get("capacity")) : null,
        photos,
        staff_roles: collectCreateRoomStaffPayload(),
        hourly_rate_cents: Number(form.get("hourly_rate_cents") || 0),
        max_booking_duration_minutes: Number(form.get("max_booking_duration_minutes") || 300),
      };

      try {
        const isEditingRoom = Boolean(editingRoomId);
        setState({ message: isEditingRoom ? "Saving room changes..." : "Creating room..." });
        if (isEditingRoom) {
          await api.adminUpdateRoom(editingRoomId, payload);
        } else {
          await api.createRoom(payload);
        }
        resetRoomForm();
        setState({ roomAvailabilityPreview: {} });
        await actions.refreshRooms(isEditingRoom ? "Room updated." : "Room created.");
      } catch (error) {
        setState({ message: error.message });
      }
    });
  }

  if (!elements.roomsGrid) {
    return;
  }

  elements.roomsGrid.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-room-action]");
    if (!button) {
      return;
    }

    const roomId = button.dataset.roomId;
    const action = button.dataset.roomAction;

    try {
      if (action === "edit") {
        const room = state.rooms.find((item) => String(item.id) === roomId);
        if (!room) {
          setState({ message: "Room not found." });
          return;
        }
          populateRoomForm(room);
          renderCreateRoomStaffOptions(state);
          window.dispatchEvent(
            new CustomEvent("admin-subpage-request", {
              detail: { group: "rooms", subpage: "editor" },
            }),
          );
          elements.roomForm?.scrollIntoView({ behavior: "smooth", block: "start" });
          setState({ message: `Editing ${room.name}.` });
          return;
        }

      if (action === "delete") {
        const roomName = button.dataset.roomName || "this room";
        const confirmed = window.confirm(`Delete ${roomName} permanently? This cannot be undone.`);
        if (!confirmed) {
          return;
        }
      }

      setState({
        message:
          action === "archive"
            ? "Archiving room..."
            : action === "restore"
              ? "Restoring room..."
              : "Deleting room...",
      });
      if (action === "archive") {
        await api.archiveRoom(roomId);
      } else if (action === "delete") {
        await api.deleteRoomPermanently(roomId);
      } else {
        await api.restoreRoom(roomId);
      }
      setState({ roomAvailabilityPreview: {} });
      await actions.refreshRooms(
        action === "archive"
          ? "Room archived."
          : action === "restore"
            ? "Room restored."
            : "Room deleted.",
      );
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

export function renderRoomsView(currentState) {
  const canManageRooms = Boolean(currentState.currentUser?.is_admin);
  if (elements.roomsToolbar) {
    elements.roomsToolbar.classList.toggle("hidden", !canManageRooms);
  }
  if (elements.showInactiveToggle) {
    elements.showInactiveToggle.checked = currentState.showInactiveRooms;
  }
  if (elements.roomsPreviewDate && elements.roomsPreviewDate.value !== currentState.roomPreviewDate) {
    elements.roomsPreviewDate.value = currentState.roomPreviewDate;
  }

  renderCreateRoomStaffOptions(currentState);

  if (!elements.roomsGrid) {
    return;
  }

  if (!currentState.rooms.length) {
    elements.roomsGrid.innerHTML = `
      <div class="empty-state">
        No rooms match this view yet. Create one from the admin panel or change the inactive filter.
      </div>
    `;
  } else {
    elements.roomsGrid.innerHTML = currentState.rooms
      .map((room) => renderRoomCard(room, canManageRooms))
      .join("");
  }

  if (elements.adminEmpty) {
    elements.adminEmpty.classList.toggle("hidden", canManageRooms);
  }
  if (elements.roomForm) {
    elements.roomForm.classList.toggle("hidden", !canManageRooms);
    if (!canManageRooms) {
      resetRoomForm();
    }
  }
}
