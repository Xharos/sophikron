<script lang="ts">
	import {
		clockSeconds,
		timetableClock,
		timetableDayBalance,
		type TimetableSettings
	} from '#lib/timetable';
	let {
		settings = $bindable(),
		locked = false
	}: { settings: TimetableSettings; locked?: boolean } = $props();
	const balance = $derived(timetableDayBalance(settings));
</script>

{#if !locked && balance}<p
		class="notification is-light"
		class:is-warning={balance.remainingSeconds > 0}
		class:is-success={balance.remainingSeconds === 0}
		role="status"
	>
		Hors pauses et fenêtre du self : {balance.teachingSeconds / 60} minutes, soit {balance.sessions} séances
		complètes de {settings.session_minutes} minutes.
		{#if balance.remainingSeconds}
			Il reste {balance.remainingSeconds / 60} minute(s) : la journée ne se découpe pas exactement en
			séances complètes.{/if}
	</p>{/if}

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
			disabled={locked}
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
			disabled={locked}
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
			disabled={locked}
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
<fieldset class="mb-5" disabled={locked}>
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
<fieldset class="mb-5" disabled={locked}>
	<legend class="label">Ouverture du self</legend>
	<p class="help mb-3">
		Les cours et khôlles restent autorisés. Chaque élève doit garder une séance entière et continue
		pour manger.
	</p>
	<div class="columns">
		<div class="column">
			<label class="label" for="lunch-start">Ouverture</label><input
				id="lunch-start"
				class="input"
				type="time"
				required
				value={timetableClock(settings.lunch_start ?? 43200)}
				oninput={(event) => (settings.lunch_start = clockSeconds(event.currentTarget.value))}
			/>
		</div>
		<div class="column">
			<label class="label" for="lunch-end">Fermeture</label><input
				id="lunch-end"
				class="input"
				type="time"
				required
				value={timetableClock(settings.lunch_end ?? 50400)}
				oninput={(event) => (settings.lunch_end = clockSeconds(event.currentTarget.value))}
			/>
		</div>
	</div>
</fieldset>
{#if locked}<p class="help mb-4">
		Horaires, pauses, durée des séances et self sont figés après création.
	</p>{/if}
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
