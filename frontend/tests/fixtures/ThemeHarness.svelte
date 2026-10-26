<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import Footer from '../../src/lib/components/Footer.svelte';
	import RoleTag from '../../src/lib/components/RoleTag.svelte';
	import SubjectTag from '../../src/lib/components/SubjectTag.svelte';
	import TagSelector from '../../src/lib/components/TagSelector.svelte';
	import VisualPicker from '../../src/lib/components/VisualPicker.svelte';
	import FormattedText from '../../src/lib/components/lessons/FormattedText.svelte';
	import { roleOptions } from '../../src/lib/roles';
	import Timelines from '../../src/lib/components/Timelines.svelte';
	import StatisticChart from '../../src/lib/components/statistics/StatisticChart.svelte';
	import { chartPalette } from '../../src/lib/statistics';
	let selected = $state<string[]>(['teacher']);
	let icon = $state('physics');
	const colors = [
		'#000000',
		'#ffffff',
		'#ffff00',
		'#777777',
		'#ff0000',
		'#00ff00',
		'#0000ff',
		'#244bc1'
	];
</script>

<main class="container p-4">
	<section class="workspace-panel">
		<h1 class="title">Une plateforme pour apprendre</h1>
		<p class="muted">Texte secondaire lisible dans les deux thèmes.</p>
		<span class="tag is-light">Votre cours</span>
		<span class="tag is-light">Éditeur</span>
		<Timelines
			site={{
				today: '2026-10-26',
				settings: {
					name: 'Sophikron',
					home_text: '',
					text_color: '#244bc1',
					holiday_color: '#ffffff',
					version: 0
				},
				timelines: [
					{
						id: 1,
						name: 'Année scolaire',
						starts_on: '2026-09-01',
						ends_on: '2027-08-31',
						color: '#ffff00',
						version: 0
					}
				],
				events: [
					{
						id: 1,
						name: 'Vacances',
						starts_on: '2026-10-01',
						ends_on: '2026-11-30',
						color: '#ffffff',
						version: 0,
						kind: 'holiday',
						timeline_ids: [1]
					}
				]
			}}
		/>
		{#each ['user', 'teacher', 'kholleur', 'admin'] as role (role)}<RoleTag {role} />{/each}
		<div class="my-4"><TagSelector options={roleOptions} bind:selected legend="Rôles" /></div>
		{#each colors as color (color)}
			<div class="mb-2">
				<SubjectTag subject={{ name: `Matière ${color}`, icon: 'science', color }} /><FormattedText
					text={`Texte ==${color}==`}
					{color}
				/>
			</div>
		{/each}
		<VisualPicker
			label="Icônes"
			bind:value={icon}
			choices={colors.map((color, index) => ({
				value: String(index),
				label: color,
				icon: 'science',
				color
			}))}
		/>
		<div class="field">
			<label class="label" for="example">Exemple de formulaire</label><input
				class="input"
				id="example"
				placeholder="Votre réponse"
			/>
		</div>
		<div class="select">
			<select aria-label="Exemple de liste"><option>Une matière</option></select>
		</div>
		<button class="button is-primary" type="button">Enregistrer</button>
		<button class="button is-light" type="button">Annuler</button>
		{#each ['success', 'warning', 'danger', 'info'] as status (status)}<p
				class="notification is-light is-{status} mt-3"
			>
				Message {status}
			</p>{/each}
		<p class="account-status">Actif</p>
		<p class="account-status pending">En attente</p>
		<table class="table is-fullwidth">
			<thead><tr><th>Matière</th><th>État</th></tr></thead><tbody
				><tr><td>Physique</td><td>Disponible</td></tr></tbody
			>
		</table>
		<StatisticChart
			title="Activité"
			labels={['Lundi', 'Mardi']}
			series={chartPalette.map((color, index) => ({
				key: String(index),
				label: `Série ${index + 1}`,
				color,
				values: [index + 1, index + 2]
			}))}
		/>
	</section>
</main>
<Footer establishmentName="Sophikron" />
