# www.clausconrad.com

This repo contains the [Quartz v4](https://quartz.jzhao.xyz/) static-site generator
configured for the `/notes/` path of www.clausconrad.com.

The `content/` directory is populated at build time by the pipeline; it should not be committed when building locally. (It cannot be added to `.gitignore` because Quartz would ignore it too.)

## Local development

```bash
npm ci
GH_TOKEN=XXXXX ./build.sh --serve
```