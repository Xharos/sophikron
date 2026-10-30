/** Relative sRGB luminance for validated six-digit colors. */
export function luminance(color: string): number {
	const channels = [1, 3, 5].map((index) => {
		const value = Number.parseInt(color.slice(index, index + 2), 16) / 255;
		return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
	});
	return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

/** WCAG contrast ratio between two opaque colors. */
export function contrastRatio(first: string, second: string): number {
	const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
	return (values[0] + 0.05) / (values[1] + 0.05);
}

/** Preserve an author's hue, adjusting only its displayed shade to reach text contrast. */
export function readableColor(color: string, background: string): string {
	const source = /^#[0-9a-f]{6}$/i.test(color) ? color : '#244bc1';
	const target = luminance(background) > 0.179 ? 0 : 255;
	for (let amount = 0; amount <= 100; amount++) {
		const result =
			'#' +
			[1, 3, 5]
				.map((index) => {
					const channel = Number.parseInt(source.slice(index, index + 2), 16);
					return Math.round(channel + ((target - channel) * amount) / 100)
						.toString(16)
						.padStart(2, '0');
				})
				.join('');
		if (contrastRatio(result, background) >= 4.5) return result;
	}
	return target ? '#ffffff' : '#000000';
}

/** Theme-aware accent for SVG charts and colored text on standard application surfaces. */
export function themeAccent(color: string): string {
	return `light-dark(${readableColor(color, '#f7f8fa')}, ${readableColor(color, '#1b2532')})`;
}
