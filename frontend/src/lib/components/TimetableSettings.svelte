<script lang="ts">
	import { clockSeconds, timetableClock, type TimetableSettings } from '#lib/timetable';
	let { settings = $bindable() }: { settings: TimetableSettings } = $props();
</script>

<div class="columns is-multiline">
	<div class="column is-half">
		<label class="label" for="year-start">Rentrée</label>
		<input id="year-start" class="input" type="date" bind:value={settings.start} required />
	</div>
	<div class="column is-half">
		<label class="label" for="year-end">Fin des cours</label>
		<input id="year-end" class="input" type="date" bind:value={settings.end} required />
	</div>
	<div class="column is-half">
		<label class="label" for="day-start">Début de journée</label>
		<input
			id="day-start"
			class="input"
			type="time"
			step="1"
			value={timetableClock(settings.day_start)}
			oninput={(event) => (settings.day_start = clockSeconds(event.currentTarget.value))}
			required
		/>
	</div>
	<div class="column is-half">
		<label class="label" for="day-end">Fin de journée</label>
		<input
			id="day-end"
			class="input"
			type="time"
			step="1"
			value={timetableClock(settings.day_end)}
			oninput={(event) => (settings.day_end = clockSeconds(event.currentTarget.value))}
			required
		/>
	</div>
	<div class="column is-half">
		<label class="label" for="session-minutes">Durée d’une séance, en minutes</label>
		<input
			id="session-minutes"
			class="input"
			type="number"
			min="10"
			max="240"
			step="1"
			bind:value={settings.session_minutes}
			required
		/>
		<p class="help">
			Demi-séance : {timetableClock(settings.session_minutes * 30)}. Les pauses ne comptent pas dans
			la durée des blocs.
		</p>
	</div>
	<div class="column is-half">
		<label class="checkbox mt-5"
			><input type="checkbox" bind:checked={settings.saturday} /> Samedi travaillé</label
		>
	</div>
</div>
<fieldset class="mb-5">
	<legend class="label">Pauses quotidiennes</legend>
	{#each settings.breaks as pause, index (index)}
		<div class="columns is-mobile is-vcentered mb-0">
			<div class="column">
				<label class="label is-small" for={`break-start-${index}`}>Début de pause {index + 1}</label
				>
				<input
					class="input"
					id={`break-start-${index}`}
					type="time"
					step="1"
					value={timetableClock(pause.start)}
					oninput={(event) => (pause.start = clockSeconds(event.currentTarget.value))}
					required
				/>
			</div>
			<div class="column">
				<label class="label is-small" for={`break-end-${index}`}>Fin de pause {index + 1}</label>
				<input
					class="input"
					id={`break-end-${index}`}
					type="time"
					step="1"
					value={timetableClock(pause.end)}
					oninput={(event) => (pause.end = clockSeconds(event.currentTarget.value))}
					required
				/>
			</div>
			<div class="column is-narrow">
				<button
					class="button is-light mt-4"
					type="button"
					aria-label={`Retirer la pause ${index + 1}`}
					onclick={() =>
						(settings.breaks = settings.breaks.filter((_, position) => position !== index))}
					>×</button
				>
			</div>
		</div>
	{/each}
	<button
		class="button is-small is-light mt-2"
		type="button"
		disabled={settings.breaks.length >= 8}
		onclick={() => (settings.breaks = [...settings.breaks, { start: 43200, end: 46800 }])}
		>Ajouter une pause</button
	>
</fieldset>
<fieldset>
	<legend class="label">Vacances et jours sans cours</legend>
	<p class="help mb-3">
		Bornes inclusives. Les semaines entièrement sans cours ne font pas avancer les cycles de deux ou
		trois semaines.
	</p>
	{#each settings.holidays as holiday, index (index)}
		<div class="box p-3">
			<label class="label is-small" for={`holiday-name-${index}`}
				>Nom de la période {index + 1}</label
			>
			<input
				class="input mb-2"
				id={`holiday-name-${index}`}
				bind:value={holiday.name}
				maxlength="100"
			/>
			<div class="columns is-mobile mb-0">
				<div class="column">
					<label class="label is-small" for={`holiday-start-${index}`}>Du</label><input
						class="input"
						id={`holiday-start-${index}`}
						type="date"
						bind:value={holiday.start}
						required
					/>
				</div>
				<div class="column">
					<label class="label is-small" for={`holiday-end-${index}`}>Au</label><input
						class="input"
						id={`holiday-end-${index}`}
						type="date"
						bind:value={holiday.end}
						required
					/>
				</div>
			</div>
			<button
				class="button is-small is-light"
				type="button"
				onclick={() =>
					(settings.holidays = settings.holidays.filter((_, position) => position !== index))}
				>Retirer cette période</button
			>
		</div>
	{/each}
	<button
		class="button is-small is-light"
		type="button"
		disabled={settings.holidays.length >= 40}
		onclick={() =>
			(settings.holidays = [
				...settings.holidays,
				{ name: 'Vacances', start: settings.start, end: settings.start }
			])}>Ajouter une période</button
	>
</fieldset>
