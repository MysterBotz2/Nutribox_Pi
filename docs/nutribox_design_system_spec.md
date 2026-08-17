# NutriBox — Design System & Theme Specification

> **Target Audience:** Frontend Engineers & AI Coding Agents building web/mobile interfaces for NutriBox.
> **Version:** 1.0.0 · **Design Philosophy:** Organic, Fresh, Premium Health & Fitness UI

---

## 1. Executive Summary & Brand Aesthetics

NutriBox uses a **fresh, clean, organic, and health-focused** design language inspired by top-tier modern diet tracking apps. 

- **Primary Accent:** Vitality Leaf Green (`#3DB35A` / `#4ECB6C`) representing clean eating and healthy habits.
- **Surface Elevation:** Soft off-white cards (`#F0F0F3` light) and deep charcoal cards (`#212225` dark).
- **Typography Concept:** Dual-font setup separating body text (clean sans-serif) from numerical metrics (soft rounded numbers for calories, grams, percentages).
- **Macro Color Coding:** Fixed, high-contrast semantic colors for quick visual parsing of Protein, Carbs, Fat, and Calories.

---

## 2. Color Palette & Token System

### 2.1 Brand & Functional Colors

| Token Name | Light Hex | Dark Hex | Role / Usage |
| :--- | :--- | :--- | :--- |
| `primary` | `#3DB35A` | `#4ECB6C` | Primary buttons, active state highlights, progress fills |
| `primary-light` | `#E8F8ED` | `#1A3D25` | Light badge backgrounds, secondary hero cards |
| `primary-muted` | `#A8DEB8` | `#2D6B3F` | Track backgrounds, disabled active states |
| `accent` | `#F5A623` | `#F5A623` | Streak fire icons, calorie highlights |
| `danger` | `#E53935` | `#EF5350` | Over-limit alerts, delete buttons |

### 2.2 Macro-Nutrient Fixed Color Scheme
*These colors remain constant regardless of light/dark mode for consistent visual memory.*

| Macro | Hex | RGB / HSL | Usage |
| :--- | :--- | :--- | :--- |
| **Calories** | `#F5A623` | `rgb(245, 166, 35)` | Calorie progress ring & calorie count text |
| **Protein** | `#4A90D9` | `rgb(74, 144, 217)` | Protein bar, pie chart slice, P tag |
| **Carbs** | `#F47D6F` | `rgb(244, 125, 111)` | Carbs bar, pie chart slice, C tag |
| **Fat** | `#F7CE68` | `rgb(247, 206, 104)` | Fat bar, pie chart slice, F tag |
| **Fiber** | `#4ECDC4` | `rgb(78, 205, 196)` | Fiber metrics |
| **Sugar** | `#C27DDA` | `rgb(194, 125, 218)` | Sugar metrics |

### 2.3 Theme Surface & Text Hierarchy

| UI Layer | Light Mode Hex | Dark Mode Hex | Tailwind Token |
| :--- | :--- | :--- | :--- |
| **App Background** | `#FFFFFF` | `#000000` | `bg-white dark:bg-black` |
| **Elevated Surface** | `#FAFAFA` | `#18191C` | `bg-surface-light dark:bg-surface-dark` |
| **Card / Container** | `#F0F0F3` | `#212225` | `bg-surface-cardLight dark:bg-surface-cardDark` |
| **Primary Text** | `#0D0D0D` | `#FFFFFF` | `text-slate-900 dark:text-white` |
| **Secondary Text** | `#60646C` | `#B0B4BA` | `text-slate-500 dark:text-slate-400` |
| **Borders & Dividers**| `#E8E8ED` | `#2C2D31` | `border-slate-200 dark:border-slate-800` |

---

## 3. Tailwind CSS Config Reference

For web apps using Tailwind CSS, add these exact extensions to your `tailwind.config.js`:

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#3DB35A",
          light: "#E8F8ED",
          dark: "#4ECB6C",
          muted: "#A8DEB8",
        },
        accent: "#F5A623",
        danger: "#E53935",
        macro: {
          calories: "#F5A623",
          protein: "#4A90D9",
          carbs: "#F47D6F",
          fat: "#F7CE68",
          fiber: "#4ECDC4",
          sugar: "#C27DDA",
        },
        surface: {
          light: "#FAFAFA",
          dark: "#18191C",
          cardLight: "#F0F0F3",
          cardDark: "#212225",
        },
      },
      fontFamily: {
        sans: ["Inter", "Spline Sans", "system-ui", "sans-serif"],
        rounded: ["ui-rounded", "SF Pro Rounded", "Fredoka", "sans-serif"],
        mono: ["ui-monospace", "monospace"],
      },
      borderRadius: {
        card: "16px",
        btn: "12px",
        pill: "9999px",
      },
    },
  },
};
```

---

## 4. Typography & Type Scale

> [!IMPORTANT]
> **Font Strategy Rule:** Use `font-rounded` specifically for numerical metrics (calories, grams, macro percentages, target numbers). Use `font-sans` for all titles, labels, subheadings, and body paragraphs.

| Style | Font Family | Size | Weight | Line Height | Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Display** | `font-rounded` | `32px` / `2rem` | 700 (Bold) | 1.2 | Hero calorie count |
| **Heading 1**| `font-sans` | `24px` / `1.5rem` | 700 (Bold) | 1.3 | Screen title (`Today`, `Meal Log`) |
| **Heading 2**| `font-sans` | `20px` / `1.25rem` | 600 (Semi-Bold) | 1.35 | Section headers (`Recent Meals`, `Ingredients`) |
| **Heading 3**| `font-sans` | `17px` / `1.06rem` | 600 (Semi-Bold) | 1.4 | Card subheadings, meal titles |
| **Body** | `font-sans` | `15px` / `0.94rem` | 400 (Regular) | 1.5 | General descriptions, notes |
| **Body Small**| `font-sans` | `13px` / `0.81rem` | 500 (Medium) | 1.4 | Macro labels, timestamps |
| **Caption** | `font-sans` | `11px` / `0.69rem` | 400 (Regular) | 1.4 | Status tags, micro badges |

---

## 5. Shape System & Border Radii

- **Cards & Container Elevation:** `rounded-[16px]` (`rounded-card`)
- **Action Buttons & Inputs:** `rounded-[12px]` (`rounded-btn`)
- **Pills, Badges & Progress Bars:** `rounded-[9999px]` (`rounded-pill`)

---

## 6. Key UI Component Rules & Snippets

### 6.1 Card Component Pattern
Cards should be soft elevated surfaces with subtle borders:
```html
<!-- Web HTML/Tailwind -->
<div class="p-6 rounded-[16px] border bg-[#F0F0F3] dark:bg-[#212225] border-slate-200/50 dark:border-slate-800/50">
  <!-- Card content -->
</div>
```

### 6.2 Macro Bar Spec
Progress bar tracks use `bg-slate-200 dark:bg-slate-800` as the background, filled with the macro color:
- **Protein Track:** Fill color `#4A90D9`
- **Carbs Track:** Fill color `#F47D6F`
- **Fat Track:** Fill color `#F7CE68`

### 6.3 Circular Calorie Ring
- **Track Stroke:** `#F0F0F3` (Light) / `#212225` (Dark)
- **Progress Stroke:** Linear Gradient from `#3DB35A` to `#4ECB6C`
- **Center Label:** Large bold rounded number (`font-rounded`) with small text `kcal left` beneath.

---

## 7. Instructions for AI Coding Agents

When generating web/React components for NutriBox:
1. Always apply `dark:` variant pairs for background, text, and border utilities.
2. Maintain exact macro hex codes (`#4A90D9` Protein, `#F47D6F` Carbs, `#F7CE68` Fat).
3. Ensure numbers have rounded typography class applied (`font-rounded`).
4. Keep container corners rounded at `16px` (`rounded-card`) and button corners at `12px` (`rounded-btn`).
