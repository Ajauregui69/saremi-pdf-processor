# SarEmi — API SOAP para clientes externos

SarEmi expone su motor de verificación documental como **servicio SOAP 1.1** para
clientes que no consumen REST/JSON (e.g. **QuickBase**). Es una capa sobre el mismo
pipeline de `/v1/verify/*` — mismos verificadores, misma base de datos, mismo
registro en blockchain.

| Recurso | URL |
|---|---|
| Endpoint SOAP | `POST http://<host>:8000/soap` |
| WSDL | `GET http://<host>:8000/soap?wsdl` |
| Content-Type | `text/xml; charset=utf-8` |

**Autenticación:** elemento `<apiKey>` dentro del body, o header HTTP `X-API-Key`.
Cada institución cliente usa su propia API key (tabla `api_keys`).

---

## Operaciones

### 1. VerifyDocument (síncrona)

Envía el documento y **espera el resultado completo** en la misma llamada.
Puede tardar 10–60 segundos (OCR + análisis de fraude + IA). Si tu plataforma
corta por timeout, usa el modo asíncrono (operación 2 + 3).

**Request:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <VerifyDocumentRequest xmlns="urn:saremi:verify:v1">
      <apiKey>TU_API_KEY</apiKey>
      <documentType>auto</documentType>
      <fileName>ine_frente.pdf</fileName>
      <fileContentBase64>JVBERi0xLjQK...</fileContentBase64>
      <clientReferenceId>expediente-1234</clientReferenceId>
    </VerifyDocumentRequest>
  </soap:Body>
</soap:Envelope>
```

- `documentType`: `auto` (auto-detección) o uno de:
  `ine, curp, bank_statement, proof_of_address, payroll, income_proof, csf, spei,
  escritura, predial, passport, acta_nacimiento, acta_matrimonio, acta_defuncion,
  rfc, cfdi, cert_libertad_gravamen, avaluo, carta_no_adeudo, licencia,
  fm_residencia, cedula_profesional`
- `fileContentBase64`: el PDF/imagen codificado en base64 (máx. 30 MB decodificado).
- `fileName`: opcional; la extensión determina el tipo de archivo (`.pdf` por defecto).
- `clientReferenceId`: opcional; identificador del expediente/usuario en tu sistema.

**Response:**

```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <VerifyDocumentResponse xmlns="urn:saremi:verify:v1">
      <verificationId>a1b2c3d4-...</verificationId>
      <documentType>ine</documentType>
      <status>verified</status>
      <confidenceScore>0.925</confidenceScore>
      <conclusion>Documento verificado correctamente...</conclusion>
      <processingTimeMs>18432</processingTimeMs>
      <checks>
        <check><name>curp_format</name><status>passed</status><detail>...</detail></check>
        ...
      </checks>
      <fraudFlags>
        <fraudFlag><code>AI_GENERATED</code><severity>critical</severity><description>...</description></fraudFlag>
      </fraudFlags>
      <warnings><warning>...</warning></warnings>
      <extractedData>
        <field><name>full_name</name><value>JUAN PÉREZ LÓPEZ</value></field>
        <field><name>curp</name><value>PELJ800101HDFRPN09</value></field>
        ...
      </extractedData>
    </VerifyDocumentResponse>
  </soap:Body>
</soap:Envelope>
```

Valores de `status`: `verified` | `invalid` | `inconclusive` | `manual_review`.

### 2. SubmitDocument (asíncrona)

Mismo request que `VerifyDocument` (elemento raíz `SubmitDocumentRequest`).
Responde **de inmediato** con el id para consultar después:

```xml
<SubmitDocumentResponse xmlns="urn:saremi:verify:v1">
  <verificationId>a1b2c3d4-...</verificationId>
  <status>processing</status>
  <message>Documento recibido. Consulte el resultado con GetVerificationResult.</message>
</SubmitDocumentResponse>
```

### 3. GetVerificationResult (polling)

```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetVerificationResultRequest xmlns="urn:saremi:verify:v1">
      <apiKey>TU_API_KEY</apiKey>
      <verificationId>a1b2c3d4-...</verificationId>
    </GetVerificationResultRequest>
  </soap:Body>
</soap:Envelope>
```

Si sigue en proceso responde `<status>processing</status>`; si terminó, responde
el mismo cuerpo que `VerifyDocumentResponse`. Recomendado: reintentar cada 10-15 s.

---

## Errores (SOAP Fault)

Los errores regresan HTTP 500 con un `<soap:Fault>` estándar:

| faultcode | Causa |
|---|---|
| `soap:Client.AuthenticationFailed` | API key inválida o ausente |
| `soap:Client.InvalidDocumentType` | `documentType` no soportado |
| `soap:Client.NotFound` | `verificationId` inexistente |
| `soap:Client.Forbidden` | La verificación pertenece a otra institución |
| `soap:Client` | XML malformado, base64 inválido, archivo muy grande, etc. |
| `soap:Server` | Error interno |

---

## Configuración en QuickBase (Pipelines)

1. Pipeline → paso **"Make Request"** (canal *Webhooks*).
2. **URL:** `http://<host-publico>:8000/soap` — **Method:** `POST`
3. **Headers:**
   - `Content-Type: text/xml; charset=utf-8`
   - `SOAPAction: urn:saremi:verify:v1/VerifyDocument` (opcional; el servidor enruta por el body)
4. **Body:** el envelope XML del ejemplo, sustituyendo `{{...}}` con campos del registro.
5. Para archivos de QuickBase: el campo *file attachment* debe convertirse a base64
   antes de insertarse en `<fileContentBase64>`.
6. **Timeout:** si el pipeline corta antes de que responda `VerifyDocument`,
   cambiar a `SubmitDocument` + un paso posterior con `GetVerificationResult`.

## Configuración por institución (entitlements del token)

Cada institución tiene un JSONB `config` en la tabla `institutions` que controla qué
puede hacer su API key:

```json
{
  "allowed_protocols": ["rest", "soap"],
  "blockchain_enabled": true,
  "allowed_document_types": ["*"]
}
```

- **allowed_protocols** — `rest`, `soap` o ambos. Un token solo-SOAP recibe HTTP 403
  en los endpoints REST, y viceversa (fault `Client.Forbidden` en SOAP).
- **blockchain_enabled** — si es `false`, las verificaciones de esa institución NO se
  registran en blockchain (el resto del pipeline no cambia).
- **allowed_document_types** — `["*"]` para todos, o lista específica
  (`["ine", "curp"]`). Aplica también al tipo resuelto por auto-detección: si el
  documento detectado no está habilitado, se rechaza con fault
  `Client.DocumentTypeNotEnabled` (SOAP) o HTTP 403 (REST).

Gestión vía API admin (Bearer token de administrador):

```
GET /admin/institutions/{id}/config           → config actual
PUT /admin/institutions/{id}/config           → merge parcial, ej:
    { "allowed_protocols": ["soap"], "blockchain_enabled": false,
      "allowed_document_types": ["ine", "curp"] }
```

Los campos no enviados se conservan. Instituciones existentes tienen el default
permisivo (todo habilitado).

## Variables de entorno relevantes

| Variable | Default | Descripción |
|---|---|---|
| `SOAP_PUBLIC_URL` | (auto) | URL pública que aparece en el `<soap:address>` del WSDL |
| `SOAP_MAX_FILE_BYTES` | 31457280 (30 MB) | Tamaño máximo del archivo decodificado |

> **Nota de despliegue:** para que QuickBase (cloud) alcance el servicio, el puerto
> 8000 debe estar expuesto públicamente (VPS, túnel tipo ngrok/cloudflared, o
> reverse proxy con TLS). Con ngrok: `ngrok http 8000` y usar la URL https generada.
