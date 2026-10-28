<script lang="ts">
	import Modal from './Modal.svelte';
	import TimetableChoice from './TimetableChoice.svelte';
	import {
		blockKinds,
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
		weekday = $bindable(0),
		phase = $bindable(1),
		scope = $bindable('one'),
		year,
		catalog,
		groups,
		promotionId,
		templateMode,
		existing,
		occurrenceOnly = false,
		busy,
		message,
		currentTeacherName = '',
		onclose,
		onkindchange,
		onsave,
		onremove
	}: {
		block: TimetableBlock;
		weekday?: number;
		phase?: number;
		scope?: 'one' | 'future';
		year: TimetableYear;
		catalog: TimetableCatalog;
		groups: TimetableGroup[];
		promotionId: number | null;
		templateMode: boolean;
		existing: boolean;
		occurrenceOnly?: boolean;
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
		(Object.entries(blockKinds) as [TimetableBlock['kind'], string][])
			.filter(([value]) => !templateMode || value !== 'kholle')
			.map(([value, label]) => ({ value, label }))
	);
	const kholleGroups = $derived(
		groups.filter((group) => group.promotion_id === promotionId && group.kind === 'kholles')
	);
	const family = $derived(block.target_kind ?? 'promotion');
	const families = $derived([
		{ value: 'promotion', label: 'Classe entière' },
		{ value: 'halves', label: 'Demis A / B' },
		{ value: 'thirds', label: 'Tiers X / Y / Z' },
		...(!templateMode && promotionId !== null
			? [{ value: 'kholles', label: 'Groupes de khôlle', disabled: !kholleGroups.length }]
			: [])
	]);
	const recipients = $derived(
		family === 'kholles'
			? kholleGroups.map((group) => ({
					value: group.number,
					label: String(group.number).padStart(3, '0')
				}))
			: Array.from({ length: family === 'halves' ? 2 : 3 }, (_, index) => ({
					value: index + 1,
					label: String.fromCharCode((family === 'halves' ? 65 : 88) + index)
				}))
	);
	const days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
	const selectedStart = $derived(
		timetableClock(year.slots[block.start_slot]?.[0] ?? year.settings.day_start)
	);
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
			value === 'promotion' ? null : value === 'kholles' ? (kholleGroups[0]?.number ?? null) : 1;
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
			disabled={busy || family === 'student' || (family === 'kholles' && !block.target_number)}
			>Enregistrer</button
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
			legend={templateMode ? 'Enseignant' : 'Enseignant ou khôlleur'}
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
		{#if family === 'halves' || family === 'thirds' || family === 'kholles'}
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
		{#if !templateMode && promotionId === null}<p class="help mb-3">
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
		{#if templateMode}
			<TimetableChoice
				legend="Jour"
				options={days
					.slice(0, year.settings.saturday ? 6 : 5)
					.map((label, value) => ({ value, label }))}
				value={weekday}
				onchange={(value) => (weekday = value)}
				disabled={busy}
			/>
		{:else}
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
		{/if}
		<div class="columns is-mobile">
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
		<TimetableChoice
			legend="Répétition"
			options={[
				...(!templateMode ? [{ value: 0, label: 'Une seule fois' }] : []),
				{ value: 1, label: 'Chaque semaine' },
				{ value: 2, label: 'Une semaine sur deux' },
				{ value: 3, label: 'Une semaine sur trois' }
			]}
			value={block.interval}
			onchange={(value) => {
				block.interval = value as TimetableBlock['interval'];
				phase = Math.min(phase, Math.max(1, value));
			}}
			disabled={busy || (existing && !templateMode && scope === 'one')}
		/>
		{#if templateMode && block.interval > 1}
			<TimetableChoice
				legend="Semaine du cycle"
				options={Array.from({ length: block.interval }, (_, index) => ({
					value: index + 1,
					label: block.interval === 2 ? (index === 0 ? 'A' : 'B') : String(index + 1)
				}))}
				value={phase}
				onchange={(value) => (phase = value)}
				disabled={busy}
			/>
		{/if}
		{#if !templateMode && block.interval}
			<div class="field">
				<label class="label" for="block-until">Jusqu’au</label>
				<input
					id="block-until"
					class="input"
					type="date"
					bind:value={block.until}
					min={block.starts_on}
					max={year.settings.end}
					disabled={existing && scope === 'one'}
				/>
			</div>
		{/if}
		{#if occurrenceOnly}<p class="help mb-3">
				Cette occurrence seulement sera modifiée. Pour modifier la semaine type, ouvrez son mode
				d’édition.
			</p>
		{:else if existing && !templateMode}
			<TimetableChoice
				legend="Appliquer à"
				options={[
					{ value: 'one', label: 'Cette occurrence seulement' },
					{ value: 'future', label: 'Celle-ci et les suivantes' }
				]}
				value={scope}
				onchange={(value) => (scope = value as 'one' | 'future')}
				disabled={busy}
			/>
		{/if}
		{#if existing}<div class="buttons mt-5">
				<button class="button is-danger is-light" type="button" disabled={busy} onclick={onremove}
					>Supprimer</button
				>
			</div>{/if}
	</form>
</Modal>

<style>
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
