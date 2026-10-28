<script lang="ts">
	import Modal from './Modal.svelte';
	import TimetableChoice from './TimetableChoice.svelte';
	import {
		blockKinds,
		clockSeconds,
		nearestTimetableSlot,
		orderedTimetableTeachers,
		timetableClock,
		type TimetableBlock,
		type TimetableCatalog,
		type TimetableGroup,
		type TimetableYear
	} from '#lib/timetable';
	let {
		block = $bindable(),
		year,
		catalog,
		groups,
		promotionId,
		existing,
		busy,
		message,
		currentTeacherName = '',
		onclose,
		onkindchange,
		onsave,
		onremove
	}: {
		block: TimetableBlock;
		year: TimetableYear;
		catalog: TimetableCatalog;
		groups: TimetableGroup[];
		promotionId: number | null;
		existing: boolean;
		busy: boolean;
		message: string;
		currentTeacherName?: string;
		onclose: () => void;
		onkindchange: (kind: TimetableBlock['kind']) => void;
		onsave: () => void;
		onremove: () => void;
	} = $props();
	const formId = $props.id();
	const kinds = $derived(
		(Object.entries(blockKinds) as [TimetableBlock['kind'], string][]).map(([value, label]) => ({
			value,
			label
		}))
	);
	const kholleGroups = $derived(
		groups.filter((group) => group.promotion_id === promotionId && group.kind === 'kholles')
	);
	const family = $derived(block.target_kind ?? 'promotion');
	const customGroups = $derived(
		groups.filter(
			(group) =>
				group.promotion_id === promotionId && group.kind === 'custom' && group.is_active !== false
		)
	);
	const families = $derived([
		{ value: 'promotion', label: 'Classe entière' },
		{ value: 'halves', label: 'Demis A / B' },
		{ value: 'thirds', label: 'Tiers X / Y / Z' },
		...(promotionId !== null
			? [
					{ value: 'kholles', label: 'Groupes de khôlle', disabled: !kholleGroups.length },
					{ value: 'custom', label: 'Groupes personnalisés', disabled: !customGroups.length }
				]
			: [])
	]);
	const recipients = $derived(
		family === 'custom'
			? customGroups.map((group) => ({
					value: group.number,
					label: group.name ?? 'Groupe personnalisé'
				}))
			: family === 'kholles'
				? kholleGroups.map((group) => ({
						value: group.number,
						label: String(group.number).padStart(3, '0')
					}))
				: Array.from({ length: family === 'halves' ? 2 : 3 }, (_, index) => ({
						value: index + 1,
						label: String.fromCharCode((family === 'halves' ? 65 : 88) + index)
					}))
	);
	const selectedStart = $derived(
		timetableClock(year.slots[block.start_slot]?.[0] ?? year.settings.day_start)
	);
	const freeTiming = $derived(block.start_time !== null && block.start_time !== undefined);
	/** Toggle exact uninterrupted times without losing the selected starting hour. */
	function chooseFreeTiming(enabled: boolean): void {
		if (enabled) {
			block.start_time = year.slots[block.start_slot]?.[0] ?? year.settings.day_start;
			block.end_time = Math.min(
				year.settings.day_end,
				block.start_time + block.duration_slots * year.settings.session_minutes * 30
			);
		} else {
			const duration = (block.end_time ?? 0) - (block.start_time ?? 0);
			chooseStart(
				nearestTimetableSlot(
					timetableClock(block.start_time ?? year.settings.day_start),
					year.slots
				)
			);
			block.duration_slots = Math.max(
				1,
				Math.min(
					year.slots.length - block.start_slot,
					Math.round(duration / (year.settings.session_minutes * 30))
				)
			);
			block.start_time = null;
			block.end_time = null;
		}
	}
	function chooseFreeStart(value: string): void {
		const duration = (block.end_time ?? 0) - (block.start_time ?? 0);
		block.start_time = clockSeconds(value);
		block.end_time = block.start_time + duration;
	}
	const unavailableTeacher = $derived(
		block.teacher_id !== null &&
			!catalog.teachers.some((teacher) => teacher.id === block.teacher_id)
	);
	const teachers = $derived(
		orderedTimetableTeachers(catalog.teachers, block.subject_id, block.kind)
	);
	function chooseKind(kind: TimetableBlock['kind']): void {
		if (
			kind !== 'kholle' &&
			block.teacher_id !== null &&
			!catalog.teachers
				.find((teacher) => teacher.id === block.teacher_id)
				?.roles?.includes('teacher')
		)
			block.teacher_id = null;
		onkindchange(kind);
	}
	function chooseFamily(value: string): void {
		block.target_kind = value as TimetableBlock['target_kind'];
		block.target_number =
			value === 'promotion'
				? null
				: value === 'custom'
					? (customGroups[0]?.number ?? null)
					: value === 'kholles'
						? (kholleGroups[0]?.number ?? null)
						: 1;
		block.target_user_id = null;
	}
	function chooseStart(slot: number): void {
		block.start_slot = Math.max(0, Math.min(year.slots.length - 1, slot));
		block.duration_slots = Math.min(block.duration_slots, year.slots.length - block.start_slot);
	}
</script>

<Modal title={existing ? 'Modifier la séance' : 'Nouvelle séance'} drawer {busy} {onclose}>
	{#snippet actions()}
		<button
			form={formId}
			class="button is-primary"
			disabled={busy ||
				family === 'student' ||
				((family === 'kholles' || family === 'custom') && !block.target_number)}>Enregistrer</button
		>
	{/snippet}
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<form
		id={formId}
		onsubmit={(event) => {
			event.preventDefault();
			onsave();
		}}
	>
		<TimetableChoice
			legend="Type de séance"
			options={kinds}
			value={block.kind}
			onchange={chooseKind}
			disabled={busy}
		/>
		<TimetableChoice
			legend="Matière"
			options={catalog.subjects.map((subject) => ({
				value: subject.id,
				label: subject.name,
				color: subject.color
			}))}
			value={block.subject_id}
			onchange={(value) => (block.subject_id = value)}
			onclear={() => (block.subject_id = null)}
			disabled={busy}
		/>
		<TimetableChoice
			legend="Enseignant ou khôlleur"
			options={teachers.map((teacher) => ({
				value: teacher.id,
				label: teacher.name,
				secondary: block.subject_id !== null && !teacher.subject_ids?.includes(block.subject_id)
			}))}
			value={block.teacher_id}
			onchange={(value) => (block.teacher_id = value)}
			onclear={() => (block.teacher_id = null)}
			disabled={busy}
		/>
		{#if unavailableTeacher}<p class="help has-text-warning mb-3" role="status">
				{currentTeacherName || 'L’enseignant affecté'} est indisponible. Choisissez son remplaçant pour
				les prochaines séances.
			</p>{/if}
		<TimetableChoice
			legend="Salle"
			options={catalog.rooms.map((room) => ({ value: room.id, label: room.name }))}
			value={block.room_id}
			onchange={(value) => (block.room_id = value)}
			onclear={() => (block.room_id = null)}
			disabled={busy}
		/>
		<TimetableChoice
			legend="Destinataires"
			options={families}
			value={family}
			onchange={chooseFamily}
			disabled={busy}
		/>
		{#if family === 'halves' || family === 'thirds' || family === 'kholles' || family === 'custom'}
			<TimetableChoice
				legend={family === 'kholles' ? 'Groupe de khôlle' : 'Groupe'}
				options={recipients}
				value={block.target_number ?? 0}
				onchange={(value) => (block.target_number = value)}
				disabled={busy}
			/>
		{/if}
		{#if family === 'student'}<p class="help has-text-warning mb-3">
				Choisissez la classe ou un groupe pour remplacer l’ancien destinataire individuel.
			</p>{/if}
		{#if promotionId === null}<p class="help mb-3">
				Les groupes de khôlle seront proposés lorsqu’une promotion sera affectée.
			</p>{/if}
		<div class="field">
			<label class="label" for="block-title">Intitulé personnalisé</label>
			<input
				id="block-title"
				class="input"
				bind:value={block.title}
				maxlength="150"
				placeholder="Nom de la matière"
			/>
			{#if block.subject_id === null}<p class="help is-danger">
					Obligatoire lorsqu’aucune matière n’est sélectionnée.
				</p>{/if}
		</div>

		<div class="field">
			<label class="label" for="block-date">Date</label>
			<input
				id="block-date"
				class="input"
				type="date"
				bind:value={block.starts_on}
				min={year.settings.start}
				max={year.settings.end}
				required
			/>
		</div>

		<label class="timing-switch mb-4"
			><input
				type="checkbox"
				role="switch"
				checked={freeTiming}
				disabled={busy}
				onchange={(event) => chooseFreeTiming(event.currentTarget.checked)}
			/>
			<span>Horaires libres</span></label
		>
		{#if freeTiming}<div class="columns is-mobile">
				<div class="column">
					<label class="label" for="free-start">Début libre</label>
					<input
						id="free-start"
						class="input"
						type="time"
						step="1"
						required
						disabled={busy}
						min={timetableClock(year.settings.day_start)}
						max={timetableClock(year.settings.day_end)}
						value={timetableClock(block.start_time ?? 0)}
						oninput={(event) => chooseFreeStart(event.currentTarget.value)}
					/>
				</div>
				<div class="column">
					<label class="label" for="free-duration">Durée libre, en minutes</label>
					<input
						id="free-duration"
						class="input"
						type="number"
						min="0.0166666667"
						step="any"
						required
						disabled={busy}
						max={(year.settings.day_end - (block.start_time ?? 0)) / 60}
						value={((block.end_time ?? 0) - (block.start_time ?? 0)) / 60}
						oninput={(event) => {
							if (Number.isFinite(event.currentTarget.valueAsNumber))
								block.end_time =
									(block.start_time ?? 0) + Math.round(event.currentTarget.valueAsNumber * 60);
						}}
					/>
				</div>
			</div>
			<p class="help mb-4">
				Heure et durée exactes, sans arrondi ni interruption aux pauses. Les contrôles de conflits
				restent actifs.
			</p>
		{:else}<div class="columns is-mobile">
				<div class="column">
					<label class="label" for="block-start">Début</label>
					<div class="clock-control">
						<button
							type="button"
							class="button is-light"
							aria-label="Créneau précédent"
							disabled={busy || block.start_slot === 0}
							onclick={() => chooseStart(block.start_slot - 1)}>−</button
						>
						<input
							id="block-start"
							class="input"
							type="time"
							step="1"
							value={selectedStart}
							required
							min={timetableClock(year.slots[0]?.[0] ?? year.settings.day_start)}
							max={timetableClock(year.slots.at(-1)?.[0] ?? year.settings.day_end)}
							onchange={(event) => {
								chooseStart(nearestTimetableSlot(event.currentTarget.value, year.slots));
								event.currentTarget.value = timetableClock(year.slots[block.start_slot][0]);
							}}
						/>
						<button
							type="button"
							class="button is-light"
							aria-label="Créneau suivant"
							disabled={busy || block.start_slot >= year.slots.length - 1}
							onclick={() => chooseStart(block.start_slot + 1)}>+</button
						>
					</div>
					<p class="help">Ajusté au créneau le plus proche.</p>
				</div>
				<div class="column">
					<label class="label" for="block-duration">Longueur, en séances</label>
					<input
						id="block-duration"
						class="input"
						type="number"
						min="0.5"
						step="0.5"
						max={(year.slots.length - block.start_slot) / 2}
						value={block.duration_slots / 2}
						required
						onchange={(event) =>
							(block.duration_slots = Math.round(event.currentTarget.valueAsNumber * 2))}
					/>
					<p class="help">Une séance : {year.settings.session_minutes} minutes, hors pauses.</p>
				</div>
			</div>
		{/if}
		<TimetableChoice
			legend="Répétition"
			options={[
				{ value: 0, label: 'Une seule fois' },
				{ value: 1, label: 'Chaque semaine' },
				{ value: 2, label: 'Une semaine sur deux' },
				{ value: 3, label: 'Une semaine sur trois' }
			]}
			value={block.interval}
			onchange={(value) => {
				block.interval = value as TimetableBlock['interval'];
			}}
			disabled={busy}
		/>

		{#if block.interval}
			<div class="field">
				<label class="label" for="block-until">Jusqu’au</label>
				<input
					id="block-until"
					class="input"
					type="date"
					bind:value={block.until}
					min={block.starts_on}
					max={year.settings.end}
					disabled={busy}
				/>
			</div>
		{/if}

		{#if existing}<div class="buttons mt-5">
				<button class="button is-danger is-light" type="button" disabled={busy} onclick={onremove}
					>Supprimer</button
				>
			</div>{/if}
	</form>
</Modal>

<style>
	.timing-switch {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		cursor: pointer;
	}
	.timing-switch input {
		appearance: none;
		flex-shrink: 0;
		width: 2.5rem;
		height: 1.4rem;
		border-radius: 2rem;
		background: var(--color-border);
		position: relative;
		cursor: pointer;
	}
	.timing-switch input::after {
		content: '';
		position: absolute;
		width: 1rem;
		height: 1rem;
		top: 0.2rem;
		left: 0.2rem;
		background: var(--color-surface);
		border-radius: 50%;
		transition: transform 0.15s;
	}
	.timing-switch input:checked {
		background: var(--color-primary);
	}
	.timing-switch input:checked::after {
		transform: translateX(1.1rem);
	}
	.timing-switch input:focus-visible {
		outline: 3px solid var(--color-primary);
		outline-offset: 3px;
	}
	.clock-control {
		display: flex;
		gap: 0.25rem;
		align-items: center;
	}
	.clock-control .input {
		min-width: 0;
	}
	.clock-control .button {
		padding-inline: 0.65rem;
	}
</style>
