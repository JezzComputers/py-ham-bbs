const fixTextSizeAdjust = () => ({
  postcssPlugin: "fix-webkit-text-size-adjust",
  Declaration(decl) {
    if (decl.prop === "-webkit-text-size-adjust" && decl.value === "100%") {
      decl.value = "none";
    }
  },
});

fixTextSizeAdjust.postcss = true;

module.exports = {
  plugins: [require("@tailwindcss/postcss"), require("autoprefixer"), fixTextSizeAdjust],
};
