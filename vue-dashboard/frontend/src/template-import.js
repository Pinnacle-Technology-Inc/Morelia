import {
  createDeviceTemplate,
  createSessionTemplateFromToml,
  importSessionTemplate,
  validateDeviceTemplateToml,
} from "./templates-api";

export function templateNameFromFilename(filename) {
  return String(filename ?? "").trim().replace(/\.(toml|json)$/i, "").trim();
}

export async function importTemplateFile(file, templateType) {
  const source = await file.text();
  const extension = String(file.name ?? "").split(".").pop()?.toLowerCase();

  if (extension === "toml") {
    if (templateType === "session") {
      return createSessionTemplateFromToml({
        name: templateNameFromFilename(file.name),
        toml: source,
      });
    }
    if (templateType === "device") {
      const validation = await validateDeviceTemplateToml(source);
      return createDeviceTemplate({
        name: validation.content?.name || templateNameFromFilename(file.name),
        type: validation.content?.type,
        parameters: validation.content?.parameters ?? {},
      });
    }
  }

  if (extension === "json") {
    const payload = JSON.parse(source);
    if (templateType === "session") return importSessionTemplate(payload);
    if (templateType === "device") return createDeviceTemplate(payload);
  }

  throw new TypeError("Choose a TOML or JSON template file.");
}
