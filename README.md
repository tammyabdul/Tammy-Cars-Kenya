# Tammy Cars Kenya — Production Starter

This version uses Flask + SQLAlchemy and is prepared for PostgreSQL/Render.

## Deploy on Render
1. Put these files in a GitHub repository.
2. In Render, create a Blueprint and select the repository.
3. Render can use `render.yaml`.
4. Set `ADMIN_USERNAME` and a strong `ADMIN_PASSWORD` when prompted.
5. Deploy.

The public site never returns `seller_phone` or `exact_location`.

## CSV import
Use these columns:
title,make,model,year,price,mileage,transmission,fuel,county,image_url,source,source_url,seller_phone,exact_location

## Important
Only import data from APIs, feeds, dealer submissions, or websites whose terms/permissions allow the intended use. Do not bypass anti-bot controls. Confirm image/content rights before republication.

Before commercial launch, add HTTPS/domain configuration, backups, rate limiting, audit logs, consent/privacy notices, and a production-grade authentication/secret-management process.

## Manual M-PESA payment
The payment page displays the configured M-PESA number. Default number is 0780555504. You can override it in Render with the `MPESA_NUMBER` environment variable. Payment verification is manual in this version; never request or store an M-PESA PIN.
