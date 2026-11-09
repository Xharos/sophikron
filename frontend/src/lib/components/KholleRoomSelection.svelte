<script lang="ts">
	let {
		subject,
		rooms,
		selected,
		onselected,
		disabled = false,
		showHeading = false
	}: {
		subject: { name: string; color: string };
		rooms: { id: number; name: string; kholle_capacity?: number }[];
		selected: number[];
		onselected: (ids: number[]) => void;
		disabled?: boolean;
		showHeading?: boolean;
	} = $props();

	/** Emit a complete room set while keeping unavailable rooms removable. */
	function toggle(room: number): void {
		if (disabled) return;
		onselected(
			selected.includes(room)
				? selected.filter((id) => id !== room)
				: [...selected, room].sort((a, b) => a - b)
		);
	}
</script>

<fieldset {disabled} style:--subject-color={subject.color}>
	<legend class="is-sr-only">Salles pour {subject.name}</legend>
	{#if showHeading}
		<div class="rooms-heading">
			<strong>Salles autorisées</strong><span>{selected.length} salle(s) sélectionnée(s)</span>
		</div>
	{/if}
	<div class="room-options">
		{#each rooms as room (room.id)}
			<label class:selected={selected.includes(room.id)}>
				<input
					type="checkbox"
					aria-label={room.name}
					disabled={room.kholle_capacity === 0 && !selected.includes(room.id)}
					checked={selected.includes(room.id)}
					onchange={() => toggle(room.id)}
				/>
				{room.name}<small
					>{room.kholle_capacity === 0
						? 'Khôlles interdites'
						: `${room.kholle_capacity ?? 1} simultanée(s)`}</small
				>
			</label>
		{/each}
	</div>
</fieldset>

<style>
	fieldset {
		border: 0;
		padding: 0;
		min-width: 0;
	}
	.rooms-heading {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.rooms-heading strong {
		color: var(--color-ink);
	}
	.room-options {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		margin: 1rem 0;
	}
	label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 1rem;
		border: var(--border-thin);
		border-radius: 8px;
		cursor: pointer;
		flex-wrap: wrap;
		max-width: 100%;
		overflow-wrap: anywhere;
	}
	label.selected {
		background: color-mix(in srgb, var(--subject-color) 12%, var(--color-surface));
		border-color: var(--subject-color);
	}
	input {
		accent-color: var(--subject-color);
	}
	fieldset:disabled label,
	label:has(input:disabled) {
		cursor: default;
	}
	input:focus-visible {
		outline: 2px solid var(--subject-color);
		outline-offset: 3px;
	}
</style>
